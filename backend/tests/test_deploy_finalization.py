"""Two independent container processes contend on an actual PostgreSQL row lock."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from time import monotonic
from uuid import uuid4

import pytest
from deploy_proxy_support import (
    ProxySession,
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


def _command(target: ProxySession, script: str, *arguments: str) -> list[str]:
    return ["docker", "exec", target.container, "python", "deploy/connection_env.py", "python", "-c",
            script, *arguments]


def test_real_postgresql_concurrent_finalize_counts_once(proxy_session: ProxySession) -> None:
    target = proxy_session
    setup = (
        "import sys,json; from sqlalchemy import select; from app.core.database import SessionLocal; "
        "from app.models import User; from app.agent.types import ChatRequest; from app.services import chat_store; "
        "s=SessionLocal(); u=s.scalar(select(User).where(User.username==sys.argv[1])); "
        "assert u is not None; uid=u.id; s.close(); "
        "cid=chat_store.prepare(uid,ChatRequest(message='S14 concurrent finalization')); "
        "print(json.dumps({'userId':uid,'conversationId':cid}))"
    )
    created = object_value(json.loads(runtime_script(target.container, setup, target.username)))
    conversation_id = str(created["conversationId"])
    hold_lock = (
        "import sys,time; from sqlalchemy import select; from app.core.database import SessionLocal; "
        "from app.models import Conversation; s=SessionLocal(); "
        "s.execute(select(Conversation).where(Conversation.id==int(sys.argv[1])).with_for_update()).scalar_one(); "
        "print('LOCKED',flush=True); time.sleep(5); s.rollback(); s.close()"
    )
    finalize = (
        "import sys,json,os; from app.agent.types import Usage; from app.services.chat_store import finalize_run; "
        "u=Usage(promptTokens=11,completionTokens=6,totalTokens=17,contextTokens=11,callCount=1); "
        "result=finalize_run(int(sys.argv[1]),int(sys.argv[2]),sys.argv[3],u,'done','race-complete','summary'); "
        "print(json.dumps({'pid':os.getpid(),'written':result,'tokens':u.conversationTotalTokens}))"
    )
    holder = subprocess.Popen(_command(target, hold_lock, conversation_id),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    workers: list[subprocess.Popen[str]] = []
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "LOCKED"
        task_id = f"s14_race_{uuid4().hex}"
        started = monotonic()
        for _ in range(2):
            workers.append(subprocess.Popen(_command(target, finalize, str(created["userId"]),
                                                      conversation_id, task_id),
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        replies = []
        for worker in workers:
            output, _diagnostic = worker.communicate(timeout=15)
            assert worker.returncode == 0, "Independent finalization process failed"
            replies.append(object_value(json.loads(output)))
        assert monotonic() - started >= 2, "Processes did not wait on the held PostgreSQL row lock"
        assert len({reply["pid"] for reply in replies}) == 2
        assert sum(reply["written"] is True for reply in replies) == 1
        assert sum(reply["written"] is False for reply in replies) == 1
        assert [reply["tokens"] for reply in replies] == [17, 17]
        terminal = target.terminal_metadata()
        assert len(terminal) == 1 and terminal[0]["totalTokens"] == 17
        metadata = object_value(terminal[0]["metadata"])
        assert metadata["taskId"] == task_id and metadata["runStatus"] == "done"
        assert object_value(metadata["usage"])["totalTokens"] == 17
    finally:
        for worker in workers:
            worker.wait(timeout=20)
        holder.wait(timeout=10)
        assert holder.returncode == 0
