"""Per-run capabilities: model arguments can never expand resource permissions."""
import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from dataclasses import asdict, is_dataclass
from importlib import import_module
from uuid import uuid4

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.adapters.cancellation import DatabaseExecutionInterrupted, DatabaseWriteOutcomeUnknown
from app.agent.cancellation import RunAborted, check_cancelled
from app.agent.output_guard import OutputArtifacts, bound_json
from app.agent.types import ChatRequest, Intent
from app.core.errors import BusinessError


class DatabaseInput(BaseModel):
    db_id: int


class StatementInput(DatabaseInput):
    statement: str


class FileInput(BaseModel):
    file_id: int


class CompareInput(BaseModel):
    pre_id: int
    test_id: int


class OutputInput(BaseModel):
    artifact_id: str
    offset: int = Field(default=0, ge=0)
    length: int = Field(default=8000, ge=1, le=16000)


class TerminateInput(BaseModel):
    reason: str


class RunTools:
    def __init__(self, user_id: int, request: ChatRequest,
                 cancel_event: threading.Event | None = None, task_id: str | None = None) -> None:
        self.user_id = user_id
        self.task_id = uuid4().hex if task_id is None else task_id
        self.database_ids = set(request.db_config_ids or [])
        self.database_ids.update(i for i in (request.pre_db_config_id, request.test_db_config_id) if i is not None)
        self.file_ids = set(request.file_ids or [])
        self.artifacts = OutputArtifacts(user_id, self.task_id)
        self.terminated = False
        self.successful_writes: set[tuple[int, str]] = set()
        self.statements_executed = 0
        self.cancel_event = cancel_event
        self.interruption: dict[str, object] | None = None
        self.completed_write_count = 0
        self.loop_stop_reason: str | None = None
        self.last_result: object = None
        self.last_output: str | None = None
        self.statement_errors: list[str] = []

    def require_database(self, db_id: int) -> None:
        if db_id not in self.database_ids:
            raise BusinessError(403, "Database was not selected for this request", 403)

    def require_file(self, file_id: int) -> None:
        if file_id not in self.file_ids:
            raise BusinessError(403, "File was not attached to this request", 403)

    def bound(self, value: object, tool_name: str | None = None) -> str:
        if isinstance(value, BaseModel):
            value = value.model_dump(by_alias=True)
        elif is_dataclass(value) and not isinstance(value, type):
            value = asdict(value)
        self.last_result = value
        self.last_output = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
        return bound_json(value, self.artifacts, tool_name=tool_name)

    async def schema(self, db_id: int) -> str:
        from app.services import database_tools

        check_cancelled(self.cancel_event)
        self.require_database(db_id)
        result = await asyncio.to_thread(database_tools.get_schema, self.user_id, db_id)
        check_cancelled(self.cancel_event)
        return self.bound(result, "getDatabaseSchema")

    async def execute(self, db_id: int, statement: str) -> str:
        from app.services import database_tools

        check_cancelled(self.cancel_event)
        self.require_database(db_id)
        signature = (db_id, statement.strip())
        if signature in self.successful_writes:
            raise BusinessError(409, "A successful write was already executed in this run")
        try:
            if self.cancel_event is None:
                result = await asyncio.to_thread(database_tools.execute_statement, self.user_id, db_id, statement)
            else:
                result = await asyncio.to_thread(database_tools.execute_statement, self.user_id, db_id, statement,
                                                 cancel_event=self.cancel_event)
        except DatabaseExecutionInterrupted as error:
            self.interruption = {
                "reason": error.reason,
                "cancelRequestSent": error.cancel_request_sent,
                "serverTerminationConfirmed": error.server_termination_confirmed,
                "writeOutcomeUnknown": error.write_outcome_unknown,
                "cancelErrorType": type(error.cancel_error).__name__ if error.cancel_error else None,
            }
            if self.cancel_event is not None:
                self.cancel_event.set()
            raise RunAborted(error.reason) from error
        except DatabaseWriteOutcomeUnknown as error:
            self.interruption = {"reason": "write_outcome_unknown", "writeOutcomeUnknown": True}
            if self.cancel_event is not None:
                self.cancel_event.set()
            raise RunAborted("write_outcome_unknown") from error
        if result.get("success") is True:
            self.statements_executed += 1
        elif result.get("success") is False:
            statement_error = result.get("error")
            if isinstance(statement_error, str):
                self.statement_errors.append(statement_error)
        if isinstance(result, dict) and result.get("success") is True and "affectedRows" in result:
            self.successful_writes.add(signature)
            self.completed_write_count += 1
        check_cancelled(self.cancel_event)
        return self.bound(result, "executeSql")

    async def compare(self, pre_id: int, test_id: int) -> str:
        check_cancelled(self.cancel_event)
        self.require_database(pre_id)
        self.require_database(test_id)
        raise BusinessError(501, "Database comparison is scheduled for a later phase")

    async def document(self, file_id: int) -> str:
        check_cancelled(self.cancel_event)
        self.require_file(file_id)
        service = import_module("app.services.file_tools")
        result = await asyncio.to_thread(service.read_file, self.user_id, file_id)
        check_cancelled(self.cancel_event)
        return self.bound(result, "readFile")

    async def image(self, file_id: int) -> str:
        check_cancelled(self.cancel_event)
        self.require_file(file_id)
        service = import_module("app.services.file_tools")
        result = await asyncio.to_thread(service.read_image, self.user_id, file_id)
        check_cancelled(self.cancel_event)
        return self.bound(result, "readImage")

    async def read_output(self, artifact_id: str, offset: int = 0, length: int = 8000) -> str:
        check_cancelled(self.cancel_event)
        page = self.artifacts.read(artifact_id, user_id=self.user_id, task_id=self.task_id,
                                   offset=offset, length=length)
        self.last_output = page
        self.last_result = json.loads(page)
        return page

    def close(self) -> None:
        self.artifacts.clear()

    async def terminate(self, reason: str) -> str:
        check_cancelled(self.cancel_event)
        self.terminated = True
        return reason

    def for_intent(self, intent: Intent) -> list[BaseTool]:
        definitions: list[tuple[str, str, type[BaseModel], Callable[..., Awaitable[str]]]] = [
            ("getDatabaseSchema", "Read selected database schema before generating statements.", DatabaseInput, self.schema),
            ("executeSql", "Execute SQL or MongoDB command on a selected database. Follow server safety rules.", StatementInput, self.execute),
            ("readToolOutput", "Page a large output using its artifactId.", OutputInput, self.read_output),
            ("doTerminate", "Finish tool execution and summarize results.", TerminateInput, self.terminate),
        ]
        if intent == "workflow":
            definitions.extend([
                ("readFile", "Read an attached document, spreadsheet, CSV or PDF.", FileInput, self.document),
                ("readImage", "OCR an attached image.", FileInput, self.image),
            ])
        if intent == "db_compare":
            definitions.append(("compareDatabases", "Compare selected source and target database structures.", CompareInput, self.compare))
        return [StructuredTool.from_function(name=name, description=description, args_schema=schema,
                                            coroutine=function) for name, description, schema, function in definitions]
