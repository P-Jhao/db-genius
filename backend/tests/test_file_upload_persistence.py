"""Storage compensation must respect the system database transaction outcome."""

import logging
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from test_file_upload import app_client as app_client_fixture

from app.core.errors import BusinessError
from app.models import UploadedFile
from app.services import file_upload

app_client = app_client_fixture


def uploaded() -> UploadFile:
    return UploadFile(filename="source.csv", file=BytesIO(b"id,name\n1,Ada\n"))


@pytest.mark.parametrize("stage", ["refresh", "commit"])
def test_postcommit_failure_keeps_metadata_and_file_readable_from_new_session(
    app_client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, stage: str,
) -> None:
    _, factory = app_client
    with factory() as session:
        original_commit = session.commit

        def fail(*_args: object, **_kwargs: object) -> None:
            if stage == "commit":
                original_commit()
            raise RuntimeError("failure after commit; sensitive database details must not be logged")

        monkeypatch.setattr(session, stage, fail)
        with caplog.at_level(logging.ERROR), pytest.raises(BusinessError) as error:
            file_upload.upload_file(session, 1, uploaded())
    assert "reference" in str(error.value.message_args)
    with factory() as independent:
        record = independent.query(UploadedFile).one()
        record_id = record.id
    saved, payload = file_upload.read_owned_bytes(1, record_id)
    assert saved.original_name == "source.csv" and payload == b"id,name\n1,Ada\n"
    assert ("committed_confirmation_failed" if stage == "refresh" else "commit_outcome_unknown") in caplog.text
    assert "sensitive database details" not in caplog.text


def test_known_uncommitted_flush_failure_cleans_storage(
    app_client: tuple[TestClient, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, factory = app_client
    with factory() as session:
        def fail(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("flush failed before commit")

        monkeypatch.setattr(session, "flush", fail)
        with pytest.raises(BusinessError):
            file_upload.upload_file(session, 1, uploaded())
    with factory() as independent:
        assert independent.query(UploadedFile).count() == 0
    assert list((tmp_path / "uploads").rglob("*.csv")) == []
