from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True)
class DbConnectionConfig:
    db_type: str
    host: str
    port: int
    db_name: str
    username: str
    password: str


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


class QueryResult(TypedDict, total=False):
    success: bool
    error: str
    sqlState: str
    errorCode: int
    rowCount: int
    data: list[dict[str, object]]
    truncated: bool
    affectedRows: int | None
    message: str
