"""Persistent credential changes use real encryption and preserve SQL edit rules."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import Base
from app.core.errors import BusinessError
from app.models import DbConfig, User
from app.schemas.db_config import DbConfigRequest
from app.services import db_config
from app.services.db_config_common import connection_for


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'credentials.sqlite'}",
                           execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_config, "_enqueue", Mock(return_value=True))
    with factory() as session:
        session.add_all([User(id=1, username="owner", password_hash="unused"),
                         User(id=2, username="outsider", password_hash="unused")])
        session.commit()
    try:
        yield factory
    finally:
        engine.dispose()
        get_settings.cache_clear()


def request(db_type: str = "mongodb", *, username: str | None = None,
            password: str | None = None) -> DbConfigRequest:
    return DbConfigRequest(name="synthetic", db_type=db_type, host="localhost", port=27017,
                           db_name="synthetic", username=username, password=password)


def test_authenticated_anonymous_and_authenticated_transitions(store: sessionmaker[Session]) -> None:
    with store() as session:
        created = db_config.create_config(session, 1, request(username="owner", password="p@:/#old"))
        config = session.get(DbConfig, created.id)
        assert config is not None and config.password_encrypted is not None
        assert config.password_encrypted != "p@:/#old"
        assert connection_for(config).password == "p@:/#old"
        changed = db_config.update_config(session, 1, created.id, request())
        assert changed.username == "" and changed.status == 0
        assert config.password_encrypted is None and connection_for(config).password == ""
        assert config.verification_version == 2
        restored = db_config.update_config(session, 1, created.id,
                                           request(username="new", password=" p@:/#new "))
        assert restored.username == "new" and config.verification_version == 3
        assert connection_for(config).password == " p@:/#new "
        assert "password" not in restored.model_dump()


@pytest.mark.parametrize("credentials", [(None, None), ("", ""), ("  ", "  ")])
def test_anonymous_creation_has_no_ciphertext(
    store: sessionmaker[Session], credentials: tuple[str | None, str | None],
) -> None:
    with store() as session:
        created = db_config.create_config(session, 1,
                                          request(username=credentials[0], password=credentials[1]))
        config = session.get(DbConfig, created.id)
        assert config is not None and config.username == "" and config.password_encrypted is None


@pytest.mark.parametrize("credentials", [("user", None), ("user", ""), ("user", "  "), (None, "p")])
def test_half_credentials_reject_without_persisting_or_erasing_old_secret(
    store: sessionmaker[Session], credentials: tuple[str | None, str | None],
) -> None:
    with store() as session:
        bad = request(username=credentials[0], password=credentials[1])
        with pytest.raises(BusinessError) as create_failure:
            db_config.create_config(session, 1, bad)
        assert create_failure.value.code == 400
        assert session.scalars(select(DbConfig)).all() == []
        created = db_config.create_config(session, 1, request(username="owner", password="old-secret"))
        config = session.get(DbConfig, created.id)
        assert config is not None
        ciphertext = config.password_encrypted
        with pytest.raises(BusinessError) as edit_failure:
            db_config.update_config(session, 1, created.id, bad)
        assert edit_failure.value.code == 400
        assert config.password_encrypted == ciphertext and config.verification_version == 1
        assert connection_for(config).password == "old-secret"


@pytest.mark.parametrize("db_type", ("mysql", "postgresql"))
def test_relational_blank_edit_keeps_accepted_ciphertext_and_ownership(
    store: sessionmaker[Session], db_type: str,
) -> None:
    with store() as session:
        created = db_config.create_config(session, 1, request(db_type, username="owner", password="old"))
        config = session.get(DbConfig, created.id)
        assert config is not None
        ciphertext = config.password_encrypted
        db_config.update_config(session, 1, created.id, request(db_type, username="owner", password=""))
        assert config.password_encrypted == ciphertext and connection_for(config).password == "old"
        with pytest.raises(BusinessError) as denied:
            db_config.update_config(session, 2, created.id, request())
        assert denied.value.code == 404
        assert config.password_encrypted == ciphertext and config.db_type == db_type
