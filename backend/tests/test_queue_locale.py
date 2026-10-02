"""Locale headers leave business task arguments and fixed document format intact."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from test_db_config_partial import metadata

from app.api.auth import database_session
from app.core.auth import current_user
from app.core.errors import BusinessError
from app.core.localization import translate
from app.core.request_locale import current_locale, locale_scope
from app.main import app
from app.models import DbConfig, User
from app.services import db_config, db_config_worker
from app.services.db_config_common import diagnostic
from app.tasks import db_config as task_module

pytest_plugins = ["test_db_config_partial"]


def run_task(config_id: int, headers: dict[str, object] | None) -> None:
    task = task_module.verify_config
    task.push_request(headers=headers)
    try:
        task.run(config_id, 1)
    finally:
        task.pop_request()


def test_scope_restores_locale_even_when_business_error_is_raised() -> None:
    with locale_scope("es"):
        with pytest.raises(BusinessError), locale_scope("ja-JP"):
            assert current_locale() == "ja"
            raise BusinessError(403, "error.trial.workflow")
        assert current_locale() == "es"
    assert current_locale() == "en"


def test_old_task_without_header_has_explicit_default_and_malformed_header_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(task_module, "verify_and_generate", lambda _id, _version: seen.append(current_locale()))
    with locale_scope("fr"):
        run_task(12, None)
        assert current_locale() == "fr"
        with pytest.raises(TypeError, match="locale must be a string"):
            run_task(12, {"locale": 42})
        assert current_locale() == "fr"
    assert seen == ["en"]


def test_concurrent_task_locales_and_exception_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = threading.Barrier(2)

    def worker(_id: int, _version: int) -> None:
        before = current_locale()
        barrier.wait(timeout=5)
        assert before == current_locale()
        raise BusinessError(403, "error.trial.workflow")

    monkeypatch.setattr(task_module, "verify_and_generate", worker)

    def invoke(locale: str) -> tuple[str, str]:
        with locale_scope(locale):
            with pytest.raises(BusinessError) as error:
                run_task(12, {"locale": locale})
            return current_locale(), diagnostic(error.value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, ["fr", "ja"]))
    assert results == [(locale, "BusinessError: " + translate("error.trial.workflow", locale))
                       for locale in ("fr", "ja")]
    assert current_locale() == "en"


def test_create_update_refresh_send_normalized_header_with_unchanged_arguments(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish = Mock()
    monkeypatch.setattr(task_module.verify_config, "apply_async", publish)

    def session_override() -> Iterator[Session]:
        with store() as session:
            yield session

    with store() as session:
        owner = session.get(User, 1)
        assert owner is not None
    app.dependency_overrides[database_session] = session_override
    app.dependency_overrides[current_user] = lambda: owner
    body = {"name": "new", "dbType": "mysql", "host": "localhost", "port": 3306,
            "dbName": "synthetic", "username": "fixture", "password": "synthetic-password"}
    try:
        client = TestClient(app)
        response = client.post("/api/db-config", headers={"Accept-Language": "fr-FR"}, json=body)
        assert response.json()["code"] == 200
        config_id = response.json()["data"]["id"]
        assert client.put(f"/api/db-config/{config_id}", headers={"Accept-Language": "ja-JP"},
                          json=body).json()["code"] == 200
        assert client.post(f"/api/db-config/{config_id}/refresh-doc",
                           headers={"Accept-Language": "zh_Hant"}).json()["code"] == 200
    finally:
        app.dependency_overrides.clear()
    calls = publish.call_args_list
    assert [call.kwargs["args"] for call in calls] == [(config_id, 1), (config_id, 2), (config_id, 3)]
    assert [call.kwargs["headers"] for call in calls] == [{"locale": "fr"}, {"locale": "ja"},
                                                        {"locale": "zh-TW"}]
    assert current_locale() == "en"


@pytest.mark.parametrize("locale", ["fr", "ja"])
@pytest.mark.parametrize("partial", [False, True])
def test_worker_preserves_fixed_status_document_and_localizes_business_errors(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, locale: str, partial: bool,
) -> None:
    adapter = Mock()
    adapter.test_connection.return_value = True
    adapter.extract_metadata.return_value = metadata(partial)
    monkeypatch.setattr(db_config_worker, "get_adapter", lambda _type: adapter)
    run_task(12, {"locale": locale})
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None and config.status == 1
        assert config.doc_content is not None and "# Database: synthetic" in config.doc_content
        assert ("Error reading metadata" in config.doc_content) is partial
        assert db_config.get_config(session, 1, 12).status_desc == "连接成功"
        config.status = 0
        session.commit()
    adapter.test_connection.side_effect = BusinessError(400, "error.dbConfig.connectionFailed")
    run_task(12, {"locale": locale})
    with store() as session:
        failed = cast(DbConfig, session.get(DbConfig, 12))
        assert failed.status == 2 and failed.doc_content is None
        assert failed.verification_error == "BusinessError: " + translate("error.dbConfig.connectionFailed", locale)
    assert current_locale() == "en"
