"""Connection diagnostics omit passwords without changing driver/asdict values."""

from dataclasses import asdict
from unittest.mock import patch

import pytest

from app.adapters.mysql import MySqlAdapter
from app.adapters.types import DbConnectionConfig


def test_config_repr_redacts_password_but_preserves_driver_and_serialization() -> None:
    password = "repr-protocol@:/+only"
    config = DbConnectionConfig("mysql", "localhost", 3306, "test", "test", password)
    assert password not in repr(config)
    assert "password=" not in repr(config)
    assert config.password == password
    assert asdict(config) == {"db_type": "mysql", "host": "localhost", "port": 3306,
                              "db_name": "test", "username": "test", "password": password}
    engine = MySqlAdapter()._engine(config, 5)
    try:
        with patch("pymysql.connect", side_effect=RuntimeError("driver entry reached")) as connect, pytest.raises(RuntimeError, match="driver entry reached"):
            engine.connect()
        assert connect.call_args.kwargs["password"] == password
    finally:
        engine.dispose()
