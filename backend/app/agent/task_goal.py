"""Strict internal goal contracts; public intent and chat protocols stay unchanged."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.types import Classification


class TableScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dbId: int = Field(gt=0)
    tables: list[str] | None

    @model_validator(mode="after")
    def validate_tables(self) -> Self:
        if self.tables is not None and (
            not self.tables or len(set(self.tables)) != len(self.tables)
            or any(not name.strip() or name != name.strip() for name in self.tables)
        ):
            raise ValueError("Named table scope must contain distinct nonempty table names")
        return self


class TaskGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["metadata_only", "statement_execution"]
    dbIds: list[int]
    tableScope: list[TableScope]
    confidence: float = Field(ge=0, le=1)
    needsClarification: bool
    reasoning: str

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if any(db_id <= 0 for db_id in self.dbIds) or len(set(self.dbIds)) != len(self.dbIds):
            raise ValueError("Goal database IDs must be distinct positive integers")
        scope_ids = [scope.dbId for scope in self.tableScope]
        if len(set(scope_ids)) != len(scope_ids) or set(scope_ids) != set(self.dbIds):
            raise ValueError("Goal table scope must cover exactly the goal databases")
        if not self.dbIds and not self.needsClarification:
            raise ValueError("An actionable database goal requires a database scope")
        return self

    def require_authorized(self, selected: set[int]) -> None:
        if not set(self.dbIds).issubset(selected):
            raise ValueError("Task goal contains a database outside the selected resources")


class ClassifiedTask(Classification):
    taskGoal: TaskGoal | None

    @model_validator(mode="after")
    def validate_goal_intent(self) -> Self:
        if (self.intent == "sql_query") != (self.taskGoal is not None):
            raise ValueError("Only sql_query classification must contain a task goal")
        return self


GOAL_RULE = """Analyze the actual current request and effective history semantically. Do not use
keyword matching to choose a goal. SQL metadata/schema inspection needs no statement execution;
any requested query of stored data or execution of a statement (including a task mixing schema
inspection with querying or writing) requires statement_execution. Merely mentioning SQL,
SELECT, DROP, a database, or a file does not authorize execution or resolve an ambiguous goal.
Use only the selected database IDs supplied in the user context. dbIds is the concrete database
scope needed for this task; tableScope has exactly one entry {dbId,tables} per dbId. tables=null
means the entire database; otherwise use the explicitly requested table names, never an empty
list. Resolve concrete follow-ups from effective history without inventing missing goals.
Set needsClarification=true for an ambiguous operation, target, or scope; confidence below 0.7
also requires clarification. Return strict JSON with all fields and no additional keys:
{mode: metadata_only|statement_execution, dbIds: integer[], tableScope: [{dbId:integer,
tables:string[]|null}], confidence: number[0,1], needsClarification:boolean, reasoning:string}.
No tools or database operations are available for this analysis."""
