"""Missing OLAP metadata must never be represented as a complete schema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from test_mysql_family import MetadataConnection, config

from app.adapters import get_adapter


class PartialMetadataConnection(MetadataConnection):
    def __init__(self, missing: str) -> None:
        super().__init__()
        self.missing = missing

    def execute(self, query: object, parameters: dict[str, str]) -> list[SimpleNamespace]:
        sql = str(query)
        if self.missing == "table listing" and "information_schema.TABLES" in sql:
            raise SQLAlchemyError("table listing unavailable")
        if "information_schema.COLUMNS" in sql:
            if self.missing == "columns":
                raise SQLAlchemyError("columns unavailable")
            if self.missing == "empty columns":
                return []
        if self.missing == "index column" and "information_schema.STATISTICS" in sql:
            return [SimpleNamespace(INDEX_NAME="expression_idx", COLUMN_NAME=None, SEQ_IN_INDEX=1)]
        return super().execute(query, parameters)

    def exec_driver_sql(self, sql: str) -> Mock:
        if self.missing == "row count" and sql.startswith("SELECT COUNT(*)"):
            raise SQLAlchemyError("count unavailable")
        return super().exec_driver_sql(sql)


@pytest.mark.parametrize("db_type", ("doris", "starrocks"))
@pytest.mark.parametrize("missing", ("table listing", "columns", "empty columns", "index column", "row count"))
def test_olap_metadata_missing_components_are_explicit(
    db_type: str, missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = get_adapter(db_type)
    connection = PartialMetadataConnection(missing)

    @contextmanager
    def connected(*_args: object) -> Iterator[PartialMetadataConnection]:
        yield connection

    monkeypatch.setattr(adapter, "_connection", connected)
    metadata = adapter.extract_metadata(config(db_type))
    assert metadata["incomplete"] is True
    assert metadata["errorMessage"] is not None
    if missing in {"table listing", "columns", "empty columns"}:
        assert metadata["tables"] == []
    else:
        assert len(metadata["tables"]) == 1
        table = metadata["tables"][0]
        assert table["columns"][0]["name"] == "id"
        if missing == "row count":
            assert table["rowCount"] is None
        else:
            assert table["indexes"] == []
    connection.rollback.assert_called_once()
