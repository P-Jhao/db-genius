"""Explicit controlled-model goal responses for execution regression scenarios."""

import json
from typing import Literal

from test_model_protocol import frame


def goal_value(db_ids: list[int] | None = None, *,
               mode: Literal["metadata_only", "statement_execution"] = "statement_execution",
               tables: list[str] | None = None, confidence: float = 0.99,
               clarify: bool = False) -> dict[str, object]:
    ids = [12] if db_ids is None else db_ids
    return {"mode": mode, "dbIds": ids,
            "tableScope": [{"dbId": db_id, "tables": tables} for db_id in ids],
            "confidence": confidence, "needsClarification": clarify,
            "reasoning": "The concrete database operation and target scope are explicit."}


def goal_reply(db_ids: list[int] | None = None, *,
               mode: Literal["metadata_only", "statement_execution"] = "statement_execution",
               tables: list[str] | None = None, confidence: float = 0.99,
               clarify: bool = False) -> list[bytes]:
    payload = goal_value(db_ids, mode=mode, tables=tables, confidence=confidence, clarify=clarify)
    return [frame({"choices": [{"delta": {"content": json.dumps(payload)}}]}), frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
            frame("[DONE]")]
