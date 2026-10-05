from collections.abc import Iterator
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.api import auth as api_auth
from app.core import auth as core_auth
from app.core import errors
from app.core.auth import utc_now
from app.core.config import Settings
from app.core.database import Base
from app.core.errors import BusinessError
from app.core.security import token_digest
from app.models import AuthSession, UploadedFile, User
from app.services import file_upload
from app.storage import backend, oss
from app.storage.local import LocalStorage
from app.storage.validation import MAX_FILE_SIZE


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([
            User(id=1, username="owner", password_hash="unused", role="user", status=1),
            User(id=2, username="other", password_hash="unused", role="user", status=1),
        ])
        session.add(AuthSession(token_hash=token_digest("owner-token"), user_id=1,
                                expires_at=utc_now() + timedelta(days=1), last_active_at=utc_now()))
        session.commit()
    monkeypatch.setattr(core_auth, "SessionLocal", factory)
    monkeypatch.setattr(file_upload, "SessionLocal", factory)
    monkeypatch.setattr(backend, "get_settings",
                        lambda: Settings(storage_backend="local", storage_root=str(tmp_path / "uploads")))

    def session_dependency() -> Iterator[Session]:
        with factory() as session:
            yield session

    main.app.dependency_overrides[api_auth.database_session] = session_dependency
    try:
        yield TestClient(main.app), factory
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def _upload(client: TestClient, name: str, data: bytes, *, token: str = "owner-token"):
    return client.post("/api/file/upload", headers={"Authorization": token},
                       files={"file": (name, BytesIO(data), "text/csv")})


def test_upload_vo_owned_read_and_missing_file(app_client: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = app_client
    assert _upload(client, "sample.csv", b"id,name\n1,Alice\n", token="bad").status_code == 401
    response = _upload(client, "sample.csv", b"id,name\n1,Alice\n")
    assert response.status_code == 200
    assert response.json()["code"] == 200
    data = response.json()["data"]
    assert set(data) == {"id", "originalName", "fileSize", "contentType", "createdAt"}
    assert data["fileSize"] == len(b"id,name\n1,Alice\n")
    assert "ossKey" not in response.text and "userId" not in response.text
    record, content = file_upload.read_owned_bytes(1, data["id"])
    assert record.original_name == "sample.csv"
    assert content == b"id,name\n1,Alice\n"
    with pytest.raises(BusinessError) as denied:
        file_upload.read_owned_bytes(2, data["id"])
    assert denied.value.code == 403
    with pytest.raises(BusinessError) as missing:
        file_upload.read_owned_bytes(1, data["id"] + 1)
    assert missing.value.code == 404
    with pytest.raises(BusinessError, match="read limit"):
        file_upload.read_owned_bytes(1, data["id"], max_bytes=2)
    with factory() as session:
        saved = session.get(UploadedFile, data["id"])
        assert saved is not None
        saved.oss_key = "uploads/2/other.csv"
        session.commit()
    with pytest.raises(BusinessError) as mismatched_key:
        file_upload.read_owned_bytes(1, data["id"])
    assert mismatched_key.value.code == 403


@pytest.mark.parametrize("name,content", [
    ("empty.csv", b""), ("bad.exe", b"hello"), ("bad.png", b"not a png"),
    ("bad.csv", b"\xff\xfe"), ("../bad.csv", b"hello"),
])
def test_rejected_uploads(app_client: tuple[TestClient, sessionmaker[Session]],
                          name: str, content: bytes) -> None:
    client, factory = app_client
    result = _upload(client, name, content)
    assert result.status_code == 200
    assert result.json()["code"] == 400
    with factory() as session:
        assert session.query(UploadedFile).count() == 0


def test_large_upload_is_bounded_without_length_assumption(
    app_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = app_client
    response = _upload(client, "huge.csv", b"x" * (MAX_FILE_SIZE + 1))
    assert response.json()["code"] == 400
    assert "20MB" in response.json()["message"]
    with factory() as session:
        assert session.query(UploadedFile).count() == 0


def test_exact_maximum_file_size_is_accepted(
    app_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = app_client
    response = _upload(client, "maximum.csv", b"x" * MAX_FILE_SIZE)
    assert response.status_code == 200
    assert response.json()["code"] == 200
    assert response.json()["data"]["fileSize"] == MAX_FILE_SIZE
    with factory() as session:
        assert session.query(UploadedFile).count() == 1


@pytest.mark.parametrize("extension,required", [
    ("xlsx", "xl/workbook.xml"), ("docx", "word/document.xml"),
])
def test_high_expansion_office_upload_is_rejected_before_decompression(
    app_client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch,
    extension: str, required: str,
) -> None:
    archive_bytes = BytesIO()
    with ZipFile(archive_bytes, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(required, "<document/>")
        archive.writestr("payload.bin", b"A" * (8 * 1024 * 1024))
    payload = archive_bytes.getvalue()
    assert len(payload) < 100_000

    def fail_if_decompressed(self: ZipFile) -> None:
        raise AssertionError("testzip must not run before archive limits")

    monkeypatch.setattr(ZipFile, "testzip", fail_if_decompressed)
    client, factory = app_client
    response = _upload(client, f"bomb.{extension}", payload)
    assert response.status_code == 200
    assert response.json()["code"] == 400
    assert "compression ratio" in response.json()["message"]
    with factory() as session:
        assert session.query(UploadedFile).count() == 0


def test_trial_upload_is_owned_and_unconfigured_oss_fails_explicitly(
    app_client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = app_client
    monkeypatch.setattr(errors, "get_settings", lambda: SimpleNamespace(trial_enabled=True))
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["id", "name"])
    sheet.append([1, "Alice"])
    stream = BytesIO()
    workbook.save(stream)
    payload = stream.getvalue()
    result = _upload(client, "sample.xlsx", payload)
    assert result.json()["code"] == 200
    record, content = file_upload.read_owned_bytes(1, result.json()["data"]["id"])
    assert record.original_name == "sample.xlsx" and content == payload
    with pytest.raises(BusinessError) as denied:
        file_upload.read_owned_bytes(2, record.id)
    assert denied.value.code == 403
    monkeypatch.setattr(backend, "get_settings", lambda: Settings(storage_backend="oss"))
    result = _upload(client, "a.csv", b"a,b\n")
    assert result.json()["code"] == 500
    assert "configured" in result.json()["message"]


def test_local_storage_blocks_escape_and_symlink(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path / "root"))
    with pytest.raises(ValueError):
        storage.put("../escape.csv", b"secret", None)
    with pytest.raises(ValueError):
        storage.read("/absolute/file.csv", 100)
    storage.put("uploads/1/safe.csv", b"safe", "text/csv")
    assert storage.read("uploads/1/safe.csv", 4) == b"safe"
    with pytest.raises(ValueError, match="read limit"):
        storage.read("uploads/1/safe.csv", 3)


def test_local_storage_rejects_cross_user_directory_symlink(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path / "root"))
    storage.put("uploads/2/other.csv", b"private", "text/csv")
    try:
        (tmp_path / "root" / "uploads" / "1").symlink_to(
            tmp_path / "root" / "uploads" / "2", target_is_directory=True,
        )
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Directory symlinks are unavailable for this test process: {exc}")
    with pytest.raises(ValueError):
        storage.read("uploads/1/other.csv", 100)
    with pytest.raises(ValueError):
        storage.put("uploads/1/new.csv", b"private", None)


def test_oss_backend_uses_configured_bucket_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    objects: dict[str, bytes] = {}

    class FakeObject:
        def __init__(self, data: bytes) -> None:
            self.data = BytesIO(data)

        def read(self, size: int) -> bytes:
            return self.data.read(size)

        def close(self) -> None:
            self.data.close()

    class FakeBucket:
        def __init__(self, auth: object, endpoint: str, bucket: str) -> None:
            assert auth == ("id", "secret")
            assert endpoint == "https://oss.example.com" and bucket == "bucket"

        def put_object(self, key: str, data: bytes, *, headers: dict[str, str] | None) -> None:
            assert headers == {"Content-Type": "text/csv"}
            objects[key] = data

        def get_object(self, key: str) -> FakeObject:
            return FakeObject(objects[key])

        def delete_object(self, key: str) -> None:
            del objects[key]

    monkeypatch.setattr(oss.oss2, "Auth", lambda key, secret: (key, secret))
    monkeypatch.setattr(oss.oss2, "Bucket", FakeBucket)
    storage = backend.get_storage(Settings(storage_backend="oss", oss_endpoint="https://oss.example.com",
                                           oss_bucket="bucket", oss_access_key_id="id",
                                           oss_access_key_secret="secret"))
    storage.put("uploads/1/object.csv", b"a,b\n", "text/csv")
    assert storage.read("uploads/1/object.csv", 4) == b"a,b\n"
    with pytest.raises(ValueError, match="read limit"):
        storage.read("uploads/1/object.csv", 3)
    storage.delete("uploads/1/object.csv")
    assert objects == {}
