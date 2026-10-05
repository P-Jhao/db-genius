"""Ordered, in-memory replay records for one SSE run; never write per token."""

from dataclasses import dataclass


@dataclass
class ReplayRecord:
    role: str
    content: str
    kind: str
    step: int
    call_id: int | None = None


class RunReplay:
    def __init__(self) -> None:
        self.records: list[ReplayRecord] = []

    def append(self, kind: str, content: object, step: int, call_id: int) -> None:
        if kind not in {"reasoning", "step"}:
            return
        if not isinstance(content, str):
            raise TypeError("Reasoning and tool replay events must be text")
        if not content:
            return
        previous = self.records[-1] if self.records else None
        if (kind == "reasoning" and previous is not None and previous.kind == kind
                and previous.call_id == call_id and previous.step == step):
            previous.content += content
            return
        self.records.append(ReplayRecord("assistant" if kind == "reasoning" else "tool",
                                         content, kind, step, call_id if kind == "reasoning" else None))
