"""Cancellation shared by the SSE producer, graph, model stream and tools."""

import threading


class RunAborted(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RunAborted("cancelled")
