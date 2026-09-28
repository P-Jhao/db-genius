"""Per-run capabilities: model arguments can never expand resource permissions."""
import asyncio
import json
from uuid import uuid4

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.agent.types import ChatRequest, Intent
from app.core.errors import BusinessError
from app.services import database_tools, file_tools


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
    def __init__(self, user_id: int, request: ChatRequest) -> None:
        self.user_id = user_id
        self.database_ids = set(request.db_config_ids or [])
        self.database_ids.update(i for i in (request.pre_db_config_id, request.test_db_config_id) if i is not None)
        self.file_ids = set(request.file_ids or [])
        self.artifacts: dict[str, str] = {}
        self.terminated = False

    def require_database(self, db_id: int) -> None:
        if db_id not in self.database_ids:
            raise BusinessError("RESOURCE_NOT_SELECTED", "Database was not selected for this request", 403)

    def require_file(self, file_id: int) -> None:
        if file_id not in self.file_ids:
            raise BusinessError("RESOURCE_NOT_SELECTED", "File was not attached to this request", 403)

    def bound(self, value: object) -> str:
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= 16000:
            return text
        artifact_id = uuid4().hex
        self.artifacts[artifact_id] = text
        return json.dumps({"artifactId": artifact_id, "totalCharacters": len(text),
                           "preview": text[:12000], "truncated": True,
                           "instruction": "Use readToolOutput to page the remaining output."}, ensure_ascii=False)

    async def schema(self, db_id: int) -> str:
        self.require_database(db_id)
        return self.bound(await asyncio.to_thread(database_tools.get_schema, self.user_id, db_id))

    async def execute(self, db_id: int, statement: str) -> str:
        self.require_database(db_id)
        return self.bound(await asyncio.to_thread(database_tools.execute_statement, self.user_id, db_id, statement))

    async def compare(self, pre_id: int, test_id: int) -> str:
        self.require_database(pre_id)
        self.require_database(test_id)
        return self.bound(await asyncio.to_thread(database_tools.compare_databases, self.user_id, pre_id, test_id))

    async def document(self, file_id: int) -> str:
        self.require_file(file_id)
        return self.bound(await asyncio.to_thread(file_tools.read_file, self.user_id, file_id))

    async def image(self, file_id: int) -> str:
        self.require_file(file_id)
        return self.bound(await asyncio.to_thread(file_tools.read_image, self.user_id, file_id))

    async def read_output(self, artifact_id: str, offset: int = 0, length: int = 8000) -> str:
        if artifact_id not in self.artifacts:
            raise BusinessError("ARTIFACT_NOT_FOUND", "Output artifact is not part of this run", 404)
        text = self.artifacts[artifact_id]
        if offset > len(text):
            raise BusinessError("INVALID_OFFSET", "Offset exceeds output length")
        return json.dumps({"content": text[offset:offset + length], "offset": offset,
                           "totalCharacters": len(text), "hasMore": offset + length < len(text)})

    async def terminate(self, reason: str) -> str:
        self.terminated = True
        return reason

    def for_intent(self, intent: Intent) -> list[BaseTool]:
        definitions = [
            ("getDatabaseSchema", "Read selected database schema before generating statements.", DatabaseInput, self.schema),
            ("executeSql", "Execute SQL or MongoDB command on a selected database. Follow server safety rules.", StatementInput, self.execute),
            ("readToolOutput", "Page a large output using its artifactId.", OutputInput, self.read_output),
            ("terminate", "Finish tool execution and summarize results.", TerminateInput, self.terminate),
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
