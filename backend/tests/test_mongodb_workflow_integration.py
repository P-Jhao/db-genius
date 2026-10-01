"""Production graph and actual Mongo service; only the HTTP model is simulated."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider
from test_mongodb_integration import mongo_target as mongo_target_fixture
from test_mongodb_interruptions import Target
from test_mongodb_workflow import answer, call, command, run
from test_mongodb_workflow import provider as provider_fixture

from app.core.config import get_settings
from app.core.database import Base
from app.core.errors import BusinessError
from app.core.security import encrypt
from app.models import DbConfig, User
from app.services import database_tools, file_tools

mongo_target = mongo_target_fixture
provider = provider_fixture


@pytest.fixture
def store(mongo_target: Target, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    _adapter, config, _client = mongo_target
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'mongo-system.sqlite'}",
                           execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_tools, "SessionLocal", factory)
    with factory() as session:
        session.add_all([User(id=7, username="owner", password_hash="unused"),
                         User(id=8, username="outsider", password_hash="unused")])
        session.add(DbConfig(id=12, user_id=7, name="synthetic Mongo", db_type="mongodb",
                             host=config.host, port=config.port, db_name=config.db_name,
                             username=config.username,
                             password_encrypted=encrypt(config.password) if config.password else None,
                             status=1, verification_version=1, builtin=False))
        session.commit()
    try:
        yield factory
    finally:
        engine.dispose()
        get_settings.cache_clear()


def tool_results(provider: Provider) -> list[dict[str, object]]:
    messages = provider.requests[-1]["messages"]
    assert isinstance(messages, list)
    outputs = [json.loads(message["content"]) for message in messages if message.get("role") == "tool"]
    assert all(isinstance(output, dict) for output in outputs)
    return outputs


@pytest.mark.asyncio
async def test_real_mongo_four_reads_through_production_workflow(
    store: sessionmaker[Session], provider: Provider,
) -> None:
    commands = [command("find", filter={"n": {"$lt": 2}}, limit=2),
                command("count", filter={"active": True}), command("distinct", field="tag"),
                command("aggregate", pipeline=[{"$group": {"_id": "$active", "count": {"$sum": 1}}},
                                                {"$sort": {"_id": 1}}])]
    for index, statement in enumerate(commands):
        provider.replies.append(call("executeSql", {"db_id": 12, "statement": statement}, f"read{index}"))
    provider.replies.append(answer("The four Mongo reads completed."))
    assert await run(provider) == "The four Mongo reads completed."
    outputs = tool_results(provider)
    assert len(outputs) == 4 and all(output["success"] is True for output in outputs)
    found = outputs[0]["result"]
    assert isinstance(found, list) and [row["n"] for row in found] == [0, 1]
    assert outputs[1]["result"] == 63
    assert outputs[2]["result"] == {"values": [f"tag-{number}" for number in range(5)]}
    assert outputs[3]["result"] == [{"_id": False, "count": 62}, {"_id": True, "count": 63}]
    assert len(provider.requests) == 5


@pytest.mark.asyncio
async def test_real_mongo_read_error_is_corrected_without_fake_success(
    store: sessionmaker[Session], provider: Provider,
) -> None:
    provider.replies = [call("executeSql", {"db_id": 12, "statement":
                                           command("count", filter={"$notAnOperator": 1})}, "bad"),
                        call("executeSql", {"db_id": 12, "statement":
                                           command("count", filter={"active": True})}, "fixed"),
                        answer("There are 63 active documents.")]
    assert await run(provider) == "There are 63 active documents."
    outputs = tool_results(provider)
    assert outputs[0]["success"] is False and outputs[0]["errorCode"] == 2
    assert "result" not in outputs[0]
    assert outputs[1]["success"] is True and outputs[1]["result"] == 63


@pytest.mark.asyncio
async def test_real_mongo_read_with_attachment_cannot_claim_import(
    store: sessionmaker[Session], mongo_target: Target, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_tools, "read_file", lambda _user, _file: {
        "success": True, "headers": ["n"], "data": [{"n": 0}], "totalRows": 1, "truncated": False,
    })
    provider.replies = [call("readFile", {"file_id": 5}, "file"),
                        call("executeSql", {"db_id": 12, "statement": command("find", limit=1)}, "read"),
                        answer("The file was completely imported.")]
    result = await run(provider, attached=True)
    assert "No database write was confirmed" in result and "completely imported" not in result
    _adapter, config, client = mongo_target
    assert client[config.db_name]["items"].count_documents({}) == 125


@pytest.mark.asyncio
async def test_real_mongo_graph_cannot_read_another_users_config(
    store: sessionmaker[Session], provider: Provider,
) -> None:
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None
        config.user_id = 8
        session.commit()
    provider.replies = [answer("I read the other database.")]
    with pytest.raises(BusinessError) as denied:
        await run(provider)
    assert denied.value.code == 404 and provider.requests == []
