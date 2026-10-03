"""Real Mongo comparison services and graph; only the HTTP model is simulated."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from pymongo import MongoClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from test_compare_graph import answer, call
from test_compare_graph import provider as provider_fixture
from test_model_protocol import Provider, model

from app.adapters.mongodb import MongoDbAdapter
from app.adapters.types import DbConnectionConfig
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import get_settings
from app.core.database import Base
from app.core.errors import BusinessError
from app.core.security import encrypt
from app.models import DbConfig, User
from app.services import database_tools, schema_diff

provider = provider_fixture
Pair = tuple[MongoClient[dict[str, object]], str, str, sessionmaker[Session]]


def snapshots(client: MongoClient[dict[str, object]], names: tuple[str, str]) -> dict[str, object]:
    return {name: {table: list(client[name][table].find({}).sort("_id", 1))
                   for table in sorted(client[name].list_collection_names())} for name in names}


@pytest.fixture
def pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Pair]:
    host, port = os.environ.get("SQLCHAT_TEST_MONGO_HOST"), os.environ.get("SQLCHAT_TEST_MONGO_PORT")
    if host is None or port is None:
        pytest.skip("dedicated Mongo target is not configured")
    if host not in {"localhost", "127.0.0.1"} or port != "17017":
        raise ValueError("Dedicated loopback Mongo target on port 17017 is required")
    username = os.environ.get("SQLCHAT_TEST_MONGO_USER", "")
    password = os.environ.get("SQLCHAT_TEST_MONGO_PASSWORD", "")
    names = (f"s12_mongo_compare_pre_{uuid4().hex}", f"s12_mongo_compare_test_{uuid4().hex}")
    configs = [DbConnectionConfig("mongodb", host, int(port), name, username, password) for name in names]
    client = MongoDbAdapter()._client(configs[0], 5)
    client.admin.command("ping")
    assert not set(names) & set(client.list_database_names())
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'comparison-system.sqlite'}",
                           execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_tools, "SessionLocal", factory)
    try:
        client[names[0]]["items"].insert_many([{"_id": n, "n": n, "label": "old"} for n in range(60)])
        client[names[0]]["retired"].insert_one({"_id": 1})
        client[names[1]]["items"].insert_many([
            {"_id": n, "n": n, "label": "new", "email": "synthetic",
             **({"late_only": "outside sample"} if n == 55 else {})} for n in range(60)
        ])
        client[names[1]]["orders"].insert_one({"_id": 1, "n": 1})
        with factory() as session:
            session.add_all([User(id=7, username="owner", password_hash="unused"),
                             User(id=8, username="outsider", password_hash="unused")])
            for identifier, config in zip((12, 13), configs, strict=True):
                session.add(DbConfig(id=identifier, user_id=7, name="synthetic Mongo comparison",
                                     db_type="mongodb", host=host, port=int(port), db_name=config.db_name,
                                     username=username, password_encrypted=encrypt(password) if password else None,
                                     status=1, verification_version=1, builtin=False))
            session.commit()
        before = snapshots(client, names)
        try:
            yield client, names[0], names[1], factory
        finally:
            assert snapshots(client, names) == before
    finally:
        for name in names:
            client.drop_database(name)
        assert not set(names) & set(client.list_database_names())
        client.close()
        engine.dispose()
        get_settings.cache_clear()


def statement(operation: str, **arguments: object) -> str:
    return json.dumps({"collection": "items", "operation": operation, **arguments})


def test_actual_schema_direction_collection_difference_and_four_read_operations(pair: Pair) -> None:
    _client, pre, test, _store = pair
    for identifier in (12, 13):
        schema = database_tools.get_schema(7, identifier)
        assert schema["schemaInferred"] is True and schema["sampleSize"] == 50 and not schema["incomplete"]
        items = next(table for table in schema["tables"] if table["name"] == "items")
        assert items["rowCount"] == 60 and "late_only" not in {column["name"] for column in items["columns"]}
    report = schema_diff.compare_databases(7, 12, 13)
    assert (report["preDatabase"], report["testDatabase"]) == (pre, test)
    assert report["preSchemaInferred"] is report["testSchemaInferred"] is True
    assert report["preSampleSize"] == report["testSampleSize"] == 50
    assert report["newTables"] == [{"table": "orders", "columnCount": 2}]
    assert report["droppedTables"] == [{"table": "retired", "columnCount": 1}]
    assert report["alteredTables"] == [{"table": "items", "changes": [
        {"change": "ADD_COLUMN", "column": "email", "type": "string"},
    ]}]
    results = [database_tools.execute_comparison_read(7, 12, query) for query in (
        statement("find", filter={"n": {"$lt": 2}}), statement("count"),
        statement("distinct", field="label"),
        statement("aggregate", pipeline=[{"$group": {"_id": None, "total": {"$sum": "$n"}}}]),
    )]
    assert results[0]["result"] == [{"_id": 0, "n": 0, "label": "old"}, {"_id": 1, "n": 1, "label": "old"}]
    assert results[1]["result"] == 60 and results[2]["result"] == {"values": ["old"]}
    assert results[3]["result"] == [{"_id": None, "total": 1770}]


def test_actual_read_service_denies_ownership_and_all_write_stages(pair: Pair) -> None:
    for query in (statement("insert"), statement("aggregate", pipeline=[{"$out": "unwanted"}]),
                  statement("aggregate", pipeline=[{"$merge": "unwanted"}]),
                  statement("aggregate", pipeline=[{"$lookup": {"from": "items", "as": "x",
                      "pipeline": [{"$merge": "unwanted"}]}}])):
        with pytest.raises(BusinessError) as denied:
            database_tools.execute_comparison_read(7, 12, query)
        assert denied.value.code == 403
    for operation in (lambda: database_tools.get_schema(8, 12),
                      lambda: database_tools.execute_comparison_read(8, 12, statement("count")),
                      lambda: schema_diff.compare_databases(8, 12, 13)):
        with pytest.raises(BusinessError) as denied:
            operation()
        assert denied.value.code == 404


async def graph(provider: Provider) -> tuple[str, list[tuple[str, object]], RunTools]:
    request = ChatRequest.model_validate({"message": "compare the observed pre and test Mongo collections",
                                          "preDbConfigId": 12, "testDbConfigId": 13,
                                          "confirmedIntent": "db_compare"})
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    tools = RunTools(7, request)
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()), tools, emit)
    return (await run_graph(context))["answer"], events, tools


@pytest.mark.asyncio
async def test_production_compare_graph_stops_sampled_schema_before_sql_migration_claim(
    pair: Pair, provider: Provider,
) -> None:
    _client, pre, test, _store = pair
    provider.replies = [call("executeSql", {"db_id": 12, "statement": statement("count")}, "read"),
                        call("compareDatabases", {"pre_id": 12, "test_id": 13}, "compare"),
                        answer("The complete schema is certain. Execute ALTER TABLE now.")]
    result, events, tools = await graph(provider)
    assert pre in result and test in result and "orders" in result and "retired" in result and "email" in result
    assert "inferred" in result.lower() and "50" in result and "unobserved fields" in result.lower()
    assert "No directly executable migration SQL" in result
    assert "complete schema is certain" not in result and "ALTER TABLE" not in result
    assert not any(kind == "summary_delta" for kind, _ in events)
    assert len(provider.requests) == 0 and tools.statements_executed == 0 and tools.completed_write_count == 0


@pytest.mark.asyncio
async def test_direction_tool_and_production_graph_reject_reverse_pair_and_other_owner(
    pair: Pair, provider: Provider,
) -> None:
    provider.replies = [call("compareDatabases", {"pre_id": 13, "test_id": 12}, "reverse")]
    tools = RunTools(7, ChatRequest(message="compare", preDbConfigId=12, testDbConfigId=13))
    try:
        compare = next(tool for tool in tools.for_intent("db_compare") if tool.name == "compareDatabases")
        with pytest.raises(BusinessError, match="direction differs"):
            await compare.ainvoke({"pre_id": 13, "test_id": 12})
    finally:
        tools.close()
    assert len(provider.requests) == 0
    with pair[3]() as session:
        config = session.get(DbConfig, 12)
        assert config is not None
        config.user_id = 8
        session.commit()
    provider.requests.clear()
    provider.replies = [call("compareDatabases", {"pre_id": 12, "test_id": 13}, "unauthorized")]
    with pytest.raises(BusinessError) as denied:
        await graph(provider)
    assert denied.value.code == 404 and len(provider.requests) == 0
