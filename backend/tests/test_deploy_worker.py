"""Actual RabbitMQ 4.3 worker control and background target verification."""

from __future__ import annotations

import json
import secrets
import subprocess
from collections.abc import Iterator
from time import monotonic, sleep
from typing import cast

import pytest
from deploy_proxy_support import (
    ProxySession,
    api,
    close_proxy_session,
    object_value,
    open_proxy_session,
    runtime_script,
)


@pytest.fixture
def proxy_session() -> Iterator[ProxySession]:
    target, thread = open_proxy_session()
    try:
        yield target
    finally:
        close_proxy_session(target, thread)


def _postgres_settings() -> dict[str, str]:
    result = subprocess.run(["docker", "inspect", "sqlchat-migration-test-postgres"],
                            capture_output=True, text=True, check=True)
    raw: object = json.loads(result.stdout)
    if not isinstance(raw, list) or len(raw) != 1:
        raise TypeError("Expected dedicated PostgreSQL container")
    config = object_value(object_value(raw[0])["Config"])
    values = config["Env"]
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise TypeError("Expected container environment entries")
    return dict(item.split("=", 1) for item in cast(list[str], values))


def _control(target: ProxySession) -> dict[str, object]:
    script = (
        "import json; from app.tasks.celery_app import celery_app as c; "
        "i=c.control.inspect(timeout=3); "
        "print(json.dumps({'ping':c.control.ping(timeout=3),'stats':i.stats(),'registered':i.registered(),"
        "'hello':i.hello('s14-control-fixture',[]),'eager':c.conf.task_always_eager}))"
    )
    return object_value(json.loads(runtime_script(target.container, script)))


def _completed(report: dict[str, object]) -> int:
    total = 0
    for value in object_value(report["stats"]).values():
        count = object_value(object_value(value)["total"]).get("sqlchat.db_config.verify", 0)
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError("Expected an integer worker task count")
        total += count
    return total


def test_real_rabbit_control_reply_mingle_and_worker_consumption(proxy_session: ProxySession) -> None:
    target = proxy_session
    before = _control(target)
    assert before["ping"] and before["hello"] and before["eager"] is False
    registered = object_value(before["registered"])
    assert all(isinstance(tasks, list) and "sqlchat.db_config.verify" in tasks for tasks in registered.values())
    database = _postgres_settings()
    completed_before = _completed(before)
    for should_succeed in (True, False):
        created = object_value(api(target.client, "POST", "db-config", json={
            "name": "S14 background success" if should_succeed else "S14 background failure",
            "dbType": "postgresql", "host": "host.docker.internal", "port": 15432,
            "dbName": database["POSTGRES_DB"], "username": database["POSTGRES_USER"],
            "password": database["POSTGRES_PASSWORD"] if should_succeed else secrets.token_urlsafe(24),
        }))
        assert created["status"] == 0, "Data source must start as pending background verification"
        config_id = created["id"]
        deadline = monotonic() + 30
        while True:
            current = object_value(api(target.client, "GET", f"db-config/{config_id}"))
            if current["status"] != 0:
                break
            assert monotonic() < deadline, "Real worker did not complete data source verification"
            sleep(0.2)
        assert current["status"] == (1 if should_succeed else 2)
        if should_succeed:
            assert current["docGeneratedAt"] is not None
            document = api(target.client, "GET", f"db-config/{config_id}/doc")
            assert isinstance(document, str) and database["POSTGRES_DB"] in document
        else:
            assert current["docContent"] is None
    after = _control(target)
    assert after["ping"] and after["hello"]
    assert _completed(after) >= completed_before + 2, "API calls were not consumed by the real worker"
