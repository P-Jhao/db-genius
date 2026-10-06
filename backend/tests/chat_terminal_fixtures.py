"""Schema-only replay of the sanitized ten-table, four-page observation."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from task_goal_fixtures import goal_reply
from test_final_report_api import final_reply
from test_model_parameters import tool_reply
from test_model_protocol import frame

from app.agent import output_guard
from app.core.config import Settings

ARTIFACT_ID = UUID(int=1).hex
PAGE_OFFSETS = (0, 3407, 6803, 10204)
DRAFT = "没有成功执行任何数据库语句。未完成：请求的数据库操作尚未完成。"
REPORT = """表清单：
ai_chat_messages
ai_conversation
ai_doc_search
ai_web_search
tb_blog_post
tb_category
tb_consultation
tb_post_tag
tb_tag
tb_user
共 10 张表，来自完整 schema 元数据；未执行 SQL。"""


def schema() -> dict[str, object]:
    value = json.loads(Path(__file__).with_name("fixtures").joinpath(
        "chat_terminal_schema.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Schema fixture must be an object")
    return value


def configure_paging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output_guard, "get_settings", lambda: Settings(tool_output_max_characters=4000))
    monkeypatch.setattr(output_guard, "uuid4", lambda: UUID(int=1))


def reasoning_reply(content: str, reasoning: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"reasoning_content": reasoning}}]}),
            *final_reply(content)]


def replies(db_id: int, *, terminate: bool, pages: int = 4) -> list[list[bytes]]:
    values = [goal_reply([db_id], mode="metadata_only")]
    values.extend(tool_reply("readToolOutput", {"artifact_id": ARTIFACT_ID, "offset": offset,
                                               "length": 8000}) for offset in PAGE_OFFSETS[:pages])
    values.append(tool_reply("doTerminate", {"reason": "done"}) if terminate else
                  reasoning_reply(DRAFT, "schema inspection complete"))
    if pages == 4:
        values.append(reasoning_reply(json.dumps({"report": REPORT, "complete": True}), "final check"))
    return values
