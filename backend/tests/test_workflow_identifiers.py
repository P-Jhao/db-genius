"""Real SQL dialect, quoted identifier and typed import regression cases."""

import json
from contextlib import contextmanager
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import UploadFile
from openpyxl import Workbook
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider
from test_workflow_integration import (
    DB_ID,
    USER_ID,
    answer_reply,
    install_target,
    run,
    target_config,
    tool_reply,
)
from test_workflow_integration import provider as provider_fixture
from test_workflow_integration import upload_store as upload_store_fixture

from app.adapters import get_adapter
from app.services import file_upload

provider = provider_fixture
upload_store = upload_store_fixture


@contextmanager
def typed_target(db_type: str):
    config = target_config(db_type)
    engine = get_adapter(db_type)._engine(config, 30)  # type: ignore[attr-defined]
    q = "`" if db_type == "mysql" else '"'
    table = f"{q}S10 Order Items {uuid4().hex[:12]}{q}"
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {table} ("
                f"{q}identifier{q} VARCHAR(20), {q}amount{q} DECIMAL(10,2), {q}label value{q} TEXT)")
        yield config, engine, table, q
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
@pytest.mark.parametrize("format,wrong_identifier", [("csv", False), ("xlsx", False), ("csv", True)])
async def test_real_special_identifiers_decimals_nulls_and_text_codes(
    db_type: str, format: str, wrong_identifier: bool, provider: Provider,
    upload_store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    if format == "csv":
        content = b"identifier,amount,label value\n001,1.00,<NULL>\n002,1.25,other\n"
        null_literal = "'<NULL>'"
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["identifier", "amount", "label value"])
        sheet.append(["001", 1, None])
        sheet.append(["002", 1.25, "other"])
        payload = BytesIO()
        workbook.save(payload)
        content, null_literal = payload.getvalue(), "NULL"
    with upload_store() as session:
        uploaded = file_upload.upload_file(session, USER_ID, UploadFile(
            filename=f"source.{format}", file=BytesIO(content)))
    with typed_target(db_type) as (config, engine, table, q):
        if wrong_identifier:
            alter = (f"ALTER TABLE {table} MODIFY {q}identifier{q} INT" if db_type == "mysql" else
                     f"ALTER TABLE {table} ALTER COLUMN {q}identifier{q} TYPE INTEGER USING {q}identifier{q}::int")
            with engine.begin() as connection:
                connection.exec_driver_sql(alter)
        install_target(monkeypatch, config)
        code = "1" if wrong_identifier else "'001'"
        insert = (f"INSERT INTO {table} ({q}identifier{q},{q}amount{q},{q}label value{q}) "
                  f"VALUES ({code},1.00,{null_literal}),('002',1.25,'other')")
        select = f"SELECT * FROM {table} ORDER BY {q}identifier{q}"
        provider.replies = [tool_reply("readFile", {"file_id": uploaded.id}, "source"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement": insert}, "write"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement": select}, "verify"),
                            tool_reply("doTerminate", {"reason": "verified"}, "done"),
                            answer_reply(json.dumps({"report": "Two rows were inserted and verified.", "complete": True}))]
        if wrong_identifier:
            alter = (f"ALTER TABLE {table} MODIFY {q}identifier{q} VARCHAR(20)" if db_type == "mysql" else
                     f"ALTER TABLE {table} ALTER COLUMN {q}identifier{q} TYPE VARCHAR(20)")
            provider.replies.insert(1, tool_reply("executeSql", {"db_id": DB_ID, "statement": alter}, "change_type"))
        result, _ = await run(provider, uploaded.id)
        with engine.connect() as connection:
            records = {row[0]: tuple(row) for row in connection.exec_driver_sql(select)}
        first = "1" if wrong_identifier else "001"
        assert records[first] == (first, Decimal("1.00"), None if format == "xlsx" else "<NULL>")
        if wrong_identifier:
            assert "do not cover the source rows" in result
            assert "Two rows were inserted and verified" not in result
        else:
            assert result == "Two rows were inserted and verified."


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_table", [False, True])
async def test_pg_case_distinct_tables_and_columns_cannot_verify_each_other(
    wrong_table: bool, provider: Provider, upload_store: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = target_config("postgresql")
    install_target(monkeypatch, config)
    engine = get_adapter("postgresql")._engine(config, 30)  # type: ignore[attr-defined]
    name = f"S10_Imports_{uuid4().hex[:12]}"
    target, other = f'"{name}"', name.lower()
    try:
        with engine.begin() as connection:
            for table in (target, other):
                connection.exec_driver_sql(f'CREATE TABLE {table} ("Name" TEXT, name TEXT)')
            connection.exec_driver_sql(f"INSERT INTO {other} VALUES ('Ada','other')")
        with upload_store() as session:
            uploaded = file_upload.upload_file(session, USER_ID, UploadFile(
                filename="case.csv", file=BytesIO(b"Name,name\nAda,other\n")))
        selected = other if wrong_table else target
        provider.replies = [tool_reply("readFile", {"file_id": uploaded.id}, "source"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement":
                                f"INSERT INTO {target} (\"Name\",name) VALUES ('Ada','other')"}, "write"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement":
                                f'SELECT "Name",name FROM {selected}'}, "verify"),
                            tool_reply("doTerminate", {"reason": "verified"}, "done"),
                            answer_reply(json.dumps({"report": "Case distinct columns were imported and verified.",
                                                     "complete": True}))]
        result, _ = await run(provider, uploaded.id)
        if wrong_table:
            assert "lack a successful subsequent SELECT" in result
        else:
            assert result == "Case distinct columns were imported and verified."
    finally:
        with engine.begin() as connection:
            for table in (target, other):
                connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        engine.dispose()
