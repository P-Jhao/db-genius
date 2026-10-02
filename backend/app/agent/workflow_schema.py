"""Per-database SQL dialect and column types from authorized schema results."""

from dataclasses import dataclass, field

from sqlglot import exp

from app.agent.workflow_mongodb import MONGODB_FORMAT, MongoWorkflowEvidence
from app.agent.workflow_values import ColumnTypes, Row

_DIALECTS = {"mysql": "mysql", "postgresql": "postgres", "sqlite": "sqlite",
             "mariadb": "mysql", "tidb": "mysql", "doris": "mysql", "starrocks": "mysql",
             "oceanbase": "mysql", "oracle": "oracle", "sqlserver": "tsql"}
TableName = tuple[str, ...]
Target = tuple[int, TableName]


def identifier_name(value: exp.Expression, dialect: str | None) -> str:
    if not value.args.get("quoted"):
        if dialect == "postgres":
            return value.name.lower()
        if dialect == "oracle":
            return value.name.upper()
    if dialect == "sqlite":
        return value.name.lower()
    return value.name


def column_name(value: exp.Expression, dialect: str | None) -> str:
    return value.name.lower() if dialect == "mysql" else identifier_name(value, dialect)


@dataclass
class WorkflowSchema:
    mongo: MongoWorkflowEvidence = field(default_factory=MongoWorkflowEvidence)
    dialects: dict[int, str] = field(default_factory=dict)
    column_types: dict[Target, ColumnTypes] = field(default_factory=dict)
    default_namespaces: dict[int, str] = field(default_factory=dict)

    def register(self, db_id: int, result: object) -> None:
        if not isinstance(result, dict):
            raise TypeError("Workflow schema must be an object")
        if self.mongo.register(db_id, result):
            self.dialects[db_id] = MONGODB_FORMAT
            return
        db_type = result.get("dbType")
        if not isinstance(db_type, str) or db_type not in _DIALECTS:
            raise ValueError("Workflow schema has an unsupported database type")
        self.dialects[db_id] = _DIALECTS[db_type]
        namespace = {"postgresql": "public", "sqlserver": "dbo"}.get(db_type)
        if namespace is None:
            namespace = result.get("schemaName", "") if db_type == "oracle" else result.get("databaseName", "")
        if not isinstance(namespace, str):
            raise TypeError("Workflow database name must be text")
        self.default_namespaces[db_id] = namespace
        tables = result.get("tables")
        if not isinstance(tables, list):
            raise TypeError("Workflow schema tables must be an array")
        self.column_types = {target: types for target, types in self.column_types.items() if target[0] != db_id}
        for table in tables:
            if not isinstance(table, dict) or not isinstance(table.get("name"), str):
                raise TypeError("Workflow schema table is invalid")
            columns = table.get("columns")
            if not isinstance(columns, list):
                raise TypeError("Workflow schema columns must be an array")
            types: ColumnTypes = {}
            for column in columns:
                if (not isinstance(column, dict) or not isinstance(column.get("name"), str) or
                        not isinstance(column.get("type"), str)):
                    raise TypeError("Workflow schema column name and type are required")
                name = column["name"].lower() if _DIALECTS[db_type] in ("mysql", "sqlite") else column["name"]
                types[name] = column["type"]
            name = table["name"].lower() if db_type == "sqlite" else table["name"]
            self.column_types[(db_id, (name,))] = types

    def table_name(self, db_id: int, table: exp.Table) -> TableName:
        dialect = self.dialects.get(db_id)
        parts = [identifier_name(value, dialect) for part in ("catalog", "db", "this")
                 if isinstance(value := table.args.get(part), exp.Identifier)]
        if len(parts) == 2 and parts[0] == self.default_namespaces.get(db_id):
            return (parts[1],)
        return tuple(parts)

    def source_row(self, db_id: int, row: Row, target_columns: set[str]) -> Row:
        """Resolve file headers against actual inserted columns; result rows remain untouched."""
        dialect = self.dialects.get(db_id)
        converted: Row = {}
        for name, value in row.items():
            target = name
            if name not in target_columns and dialect == "oracle" and name.upper() in target_columns:
                target = name.upper()
            if name not in target_columns and dialect == "tsql":
                matches = [column for column in target_columns if column.casefold() == name.casefold()]
                if len(matches) == 1:
                    target = matches[0]
            if target in converted:
                raise ValueError("File headers collide under the target column mapping")
            converted[target] = value
        return converted

    def created_table(self, db_id: int, statement: exp.Expression) -> None:
        if not isinstance(statement, exp.Create) or not isinstance(statement.this, exp.Schema):
            return
        table = statement.this.this
        if not isinstance(table, exp.Table):
            return
        target = (db_id, self.table_name(db_id, table))
        if target in self.column_types:
            return
        types: ColumnTypes = {}
        for column in statement.this.expressions:
            if isinstance(column, exp.ColumnDef) and isinstance(column.kind, exp.DataType):
                types[column_name(column.this, self.dialects.get(db_id))] = column.kind.sql(
                    dialect=self.dialects.get(db_id),
                )
        self.column_types[target] = types
