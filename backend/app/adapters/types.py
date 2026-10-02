import threading
from dataclasses import dataclass, field
from typing import NotRequired, Protocol, TypedDict


@dataclass(frozen=True)
class DbConnectionConfig:
    db_type: str
    host: str
    port: int
    db_name: str
    username: str
    password: str = field(repr=False)


class ColumnMetadata(TypedDict):
    name: str
    type: str
    nullable: bool
    primaryKey: bool
    comment: str | None


class IndexMetadata(TypedDict):
    name: str
    columns: list[str]


class TableMetadata(TypedDict):
    name: str
    comment: str | None
    rowCount: int | None
    columns: list[ColumnMetadata]
    indexes: list[IndexMetadata]


class SchemaMetadata(TypedDict):
    dbType: str
    databaseName: str
    host: str
    port: int
    tables: list[TableMetadata]
    incomplete: bool
    errorMessage: str | None
    schemaInferred: NotRequired[bool]
    sampleSize: NotRequired[int]
    schemaName: NotRequired[str]


class QueryResult(TypedDict, total=False):
    success: bool
    error: str
    sqlState: str
    errorCode: int
    rowCount: int
    data: list[dict[str, object]]
    result: list[dict[str, object]] | int | dict[str, object]
    truncated: bool
    affectedRows: int | None
    message: str


class DatabaseAdapter(Protocol):
    db_type: str

    def validate_config(self, config: DbConnectionConfig) -> None: ...

    def test_connection(self, config: DbConnectionConfig) -> bool: ...

    def is_read_only(self, statement: str) -> bool: ...

    def extract_metadata(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> SchemaMetadata: ...

    def generate_document(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> str: ...

    def execute(self, config: DbConnectionConfig, statement: str, *, trial_mode: bool = False,
                timeout_seconds: int = 30, max_rows: int = 100,
                cancel_event: threading.Event | None = None) -> QueryResult: ...
