"""Public incomplete-report errors select seven languages without leaking framing."""

import asyncio
import json
import threading
from typing import cast

import pytest

from app.agent.final_report import IncompleteFinalReport
from app.agent.graph import RunContext
from app.agent.model import CompatibleChatModel
from app.agent.types import ChatRequest, Usage
from app.api import chat
from app.services import chat_store
from app.services.chat_records import ReplayRecord


@pytest.mark.parametrize(("locale", "prefix", "retained", "review"), [
    ("en-US", "The final report could not be completed.", "does not roll back completed writes", "Review the execution steps"),
    ("zh-CN", "最终报告未能完整生成。", "不会撤销已经完成的写入", "请先查看执行步骤"),
    ("zh-HK", "最終報告未能完整產生。", "不會撤銷已完成的寫入", "請先查看執行步驟"),
    ("fr-FR", "Le rapport final n’a pas pu être terminé.", "n’annule pas les écritures déjà effectuées", "Consultez les étapes"),
    ("ms-MY", "Laporan akhir tidak dapat disiapkan.", "tidak membatalkan penulisan yang telah selesai", "Semak langkah"),
    ("ja-JP", "最終レポートを完成できませんでした。", "完了済みの書き込みが取り消されることはありません", "実行手順を確認"),
    ("es-ES", "No se pudo completar el informe final.", "no revierte las escrituras ya completadas", "Revise los pasos"),
])
@pytest.mark.asyncio
async def test_api_incomplete_report_public_message_and_persistence(
    monkeypatch: pytest.MonkeyPatch, locale: str, prefix: str, retained: str, review: str,
) -> None:
    finalized: list[tuple[str, str, str, dict[str, object]]] = []

    async def failed(context: RunContext) -> dict[str, object]:
        context.tools.completed_write_count = 1
        raise IncompleteFinalReport("test-secret-value")

    def finalize(_user: int, _conversation: int, _task: str, _usage: Usage,
                 status: str, content: str, kind: str, details: dict[str, object],
                 records: list[ReplayRecord] | None = None) -> bool:
        finalized.append((status, content, kind, details))
        return True

    monkeypatch.setattr(chat, "run_graph", failed)
    monkeypatch.setattr(chat_store, "prepare", lambda *_args: 1)
    monkeypatch.setattr(chat_store, "save", lambda *_args: None)
    monkeypatch.setattr(chat_store, "finalize_run", finalize)
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    await chat._produce(queue, 7, ChatRequest(message="report", dbConfigIds=[12],
                                            confirmedIntent="sql_query"), [], locale,
                        cast(CompatibleChatModel, object()), None, threading.Event())
    events: list[dict[str, object]] = []
    while (packet := await queue.get()) is not None:
        events.append(json.loads(packet.decode().removeprefix("data: ")))
    assert [event["type"] for event in events] == ["conversation", "usage", "error", "done"]
    message = events[-2]["content"]
    assert isinstance(message, str) and message.startswith(prefix)
    assert retained in message and review in message
    assert str(events[-2]["taskId"]) in message
    assert all(marker not in message for marker in ("test-secret-value", "DSML", "invalid_report_envelope", '"complete"'))
    assert finalized == [("error", message, "error", {"completedWriteCount": 1})]
