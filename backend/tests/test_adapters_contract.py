from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.adapters import DbConnectionConfig, get_adapter
from app.adapters.document import render_document
from app.adapters.relational import _json_value
from app.adapters.types import SchemaMetadata


def test_config_validation_and_special_password_url() -> None:
    adapter = get_adapter("postgresql")
    config = DbConnectionConfig("postgresql", "localhost", 15432, "test", "user", "p@:/#word")
    with patch("app.adapters.relational.create_engine") as create:
        adapter._engine(config, 30)
        url = create.call_args.args[0]
        assert url.password == "p@:/#word"
        assert "p%40%3A%2F%23word" in url.render_as_string(hide_password=False)
    for broken in (DbConnectionConfig("postgresql", "", 15432, "test", "user", "pw"),
                   DbConnectionConfig("postgresql", "localhost", 0, "test", "user", "pw"),
                   DbConnectionConfig("postgresql", "localhost", 15432, "test", "user", "")):
        with pytest.raises(ValueError):
            adapter.validate_config(broken)


def test_registry_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        get_adapter("sqlite")


def test_result_normalization_preserves_precision() -> None:
    assert _json_value({"amount": Decimal("123.4500"), "day": date(2026, 9, 29),
                        "bytes": b"abc"}) == {"amount": "123.4500", "day": "2026-09-29",
                                            "bytes": "YWJj"}
    assert _json_value(float("nan")) == "nan"
    assert _json_value(float("inf")) == "inf"
    with pytest.raises(TypeError):
        _json_value(object())


def test_incomplete_document_is_explicit() -> None:
    metadata: SchemaMetadata = {"dbType": "postgresql", "databaseName": "test", "host": "localhost",
                                "port": 5432, "tables": [], "incomplete": True,
                                "errorMessage": "orders: permission denied"}
    document = render_document(metadata)
    assert "# Database: test" in document
    assert "**Error reading metadata:** orders: permission denied" in document
