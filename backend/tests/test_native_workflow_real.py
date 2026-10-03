"""Real native file imports through storage, HTTP model protocol and LangGraph."""

from __future__ import annotations

import json
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import UploadFile
from native_database_fixtures import oracle_target as oracle_fixture
from native_database_fixtures import sqlserver_target as sqlserver_fixture
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider
from test_workflow_integration import DB_ID, USER_ID, answer_reply, install_target, run, tool_reply
from test_workflow_integration import provider as provider_fixture
from test_workflow_integration import upload_store as upload_store_fixture

from app.adapters.types import DbConnectionConfig
from app.services import file_upload

oracle_target = oracle_fixture
sqlserver_target = sqlserver_fixture
provider = provider_fixture
upload_store = upload_store_fixture


def fixture_target(request: pytest.FixtureRequest, db_type: str) -> tuple[DbConnectionConfig, Engine]:
    value = request.getfixturevalue(db_type + "_target")
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError("Native target fixture is invalid")
    config, engine = value
    if not isinstance(config, DbConnectionConfig) or not isinstance(engine, Engine):
        raise TypeError("Native fixture config/engine is invalid")
    return config, engine


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type,spelling", [("oracle", "upper"), ("oracle", "lower"),
                                             ("oracle", "mixed"), ("sqlserver", "bracket")])
async def test_actual_unicode_file_import_and_verification(
    db_type: str, spelling: str, request: pytest.FixtureRequest, provider: Provider,
    upload_store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = fixture_target(request, db_type)
    base = "native_file_" + uuid4().hex[:12]
    if spelling == "upper":
        table, columns, headers = base, ["id", "note", "amount"], ["id", "note", "amount"]
    elif spelling == "lower":
        table, columns, headers = f'"{base}"', ['"id"', '"note"', '"amount"'], ["id", "note", "amount"]
    elif spelling == "mixed":
        table, columns, headers = f'"Mixed_{base}"', ['"Id"', '"Note"', '"Amount"'], ["Id", "Note", "Amount"]
    else:
        table, columns, headers = f"[dbo].[{base}]", ["[id]", "[note]", "[amount]"], ["id", "note", "amount"]
    text_type = "VARCHAR2(20)" if db_type == "oracle" else "VARCHAR(20)"
    unicode_type = "NVARCHAR2(40)" if db_type == "oracle" else "NVARCHAR(40)"
    decimal_type = "NUMBER(12,2)" if db_type == "oracle" else "DECIMAL(12,2)"
    created = False
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {table} ({columns[0]} {text_type}, {columns[1]} {unicode_type}, {columns[2]} {decimal_type})")
        created = True
        content = (",".join(headers) + "\n001,中文,1.00\n002,验证,1.25\n").encode()
        with upload_store() as session:
            uploaded = file_upload.upload_file(session, USER_ID, UploadFile(filename="native.csv", file=BytesIO(content)))
        install_target(monkeypatch, config)
        write1 = f"INSERT INTO {table} ({','.join(columns)}) VALUES ('001',N'中文',1.00)"
        write2 = f"INSERT INTO {table} ({','.join(columns)}) VALUES ('002',N'验证',1.25)"
        select = f"SELECT {','.join(columns)} FROM {table} ORDER BY {columns[0]}"
        provider.replies = [tool_reply("readFile", {"file_id": uploaded.id}, "source"),
            tool_reply("executeSql", {"db_id": DB_ID, "statement": write1}, "write1"),
            tool_reply("executeSql", {"db_id": DB_ID, "statement": write2}, "write2"),
            tool_reply("executeSql", {"db_id": DB_ID, "statement": select}, "verify"),
            tool_reply("doTerminate", {"reason": "verified"}, "done"),
            answer_reply(json.dumps({"report": "Two Unicode rows were imported and verified.", "complete": True}))]
        result, _events = await run(provider, uploaded.id)
        assert result == "Two Unicode rows were imported and verified."
        with engine.connect() as connection:
            actual = [tuple(row) for row in connection.exec_driver_sql(select)]
        assert [(row[0], row[1], str(row[2])) for row in actual] == [
            ("001", "中文", "1" if db_type == "oracle" else "1.00"), ("002", "验证", "1.25")]
    finally:
        if created:
            with engine.begin() as connection:
                suffix = " PURGE" if db_type == "oracle" else ""
                connection.exec_driver_sql(f"DROP TABLE {table}{suffix}")
