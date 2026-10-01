"""MongoDB credential boundary alongside the unchanged relational requirement."""

from typing import cast
from unittest.mock import Mock

import pytest

from app.core.errors import BusinessError
from app.models import DbConfig
from app.schemas.db_config import DbConfigRequest
from app.services import db_config
from app.services.db_config_common import connection_for, validate_request


def request(db_type: str, *, username: str | None = None,
            password: str | None = None) -> DbConfigRequest:
    return DbConfigRequest(name="sample", db_type=db_type, host="localhost", port=27017,
                           db_name="sample", username=username, password=password)


def test_mongodb_optional_credentials_and_relational_required() -> None:
    assert validate_request(request("mongodb"), "").username == ""
    assert validate_request(request("mongodb", username="u"), "p").password == "p"
    with pytest.raises(BusinessError):
        validate_request(request("mongodb", username="u"), "")
    with pytest.raises(BusinessError):
        validate_request(request("mysql"), "p")
    with pytest.raises(BusinessError):
        validate_request(request("postgresql", username="u"), "")


def test_connection_for_only_allows_missing_secret_on_mongodb() -> None:
    mongo = DbConfig(db_type="mongodb", host="localhost", port=27017, db_name="sample",
                     username="", password_encrypted=None)
    assert connection_for(mongo).password == ""
    relation = DbConfig(db_type="mysql", host="localhost", port=3306, db_name="sample",
                        username="u", password_encrypted=None)
    with pytest.raises(ValueError, match="credential is missing"):
        connection_for(relation)


def test_create_and_switch_to_no_auth_clears_old_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Mock()
    monkeypatch.setattr(db_config, "deny_trial", Mock())
    monkeypatch.setattr(db_config, "_enqueue", Mock())
    monkeypatch.setattr(db_config, "to_vo", lambda config: config)
    monkeypatch.setattr(db_config, "encrypt", lambda password: f"encrypted:{password}")
    created = cast(DbConfig, db_config.create_config(session, 1, request("mongodb")))
    assert created.username == "" and created.password_encrypted is None
    with pytest.raises(BusinessError, match="password is required"):
        db_config.create_config(session, 1, request("mysql", username="u"))

    old = DbConfig(user_id=1, name="sample", db_type="mongodb", host="localhost", port=27017,
                   db_name="sample", username="old", password_encrypted="encrypted:old",
                   status=1, verification_version=1)
    monkeypatch.setattr(db_config, "mutable_config", lambda *_args: old)
    changed = cast(DbConfig, db_config.update_config(session, 1, 3, request("mongodb")))
    assert changed.username == "" and changed.password_encrypted is None
    assert connection_for(changed).password == ""
