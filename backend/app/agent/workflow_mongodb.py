"""JSON read evidence for Mongo workflows, without SQL dialect emulation."""

from dataclasses import dataclass, field

from app.adapters.mongodb_command import parse_command

MONGODB_FORMAT = "mongodb"


def schema_mutation(statement: str) -> bool:
    """Validated Mongo commands are read-only; never pass them to SQLGlot."""
    parse_command(statement)
    return False


@dataclass
class MongoWorkflowEvidence:
    database_ids: set[int] = field(default_factory=set)
    read_counts: dict[int, int] = field(default_factory=dict)
    failures: dict[int, str] = field(default_factory=dict)

    def register(self, db_id: int, result: object) -> bool:
        if not isinstance(result, dict) or result.get("dbType") != "mongodb":
            return False
        if not isinstance(db_id, int) or isinstance(db_id, bool):
            raise TypeError("Mongo workflow database ID must be an integer")
        tables = result.get("tables")
        if not isinstance(tables, list):
            raise TypeError("Mongo workflow schema tables must be an array")
        for table in tables:
            if not isinstance(table, dict) or not isinstance(table.get("name"), str):
                raise TypeError("Mongo workflow collection name must be text")
            columns = table.get("columns")
            if not isinstance(columns, list):
                raise TypeError("Mongo workflow collection columns must be an array")
            if any(not isinstance(column, dict) or not isinstance(column.get("name"), str) or
                   not isinstance(column.get("type"), str) for column in columns):
                raise TypeError("Mongo workflow field name and BSON type are required")
        self.database_ids.add(db_id)
        return True

    def before_command(self, db_id: int, statement: str) -> bool:
        if db_id not in self.database_ids:
            return False
        parse_command(statement)
        return True

    def after_command(self, db_id: int, statement: str, result: object) -> bool:
        if not self.before_command(db_id, statement):
            return False
        if not isinstance(result, dict) or "marker" in result:
            raise TypeError("Mongo workflow requires the full service result")
        if result.get("success") is not True:
            error = result.get("error")
            if not isinstance(error, str):
                raise TypeError("Mongo workflow failed result requires an error message")
            self.failures[db_id] = error
            return True
        command = parse_command(statement)
        payload = result.get("result")
        count = result.get("rowCount")
        if command.operation in {"find", "aggregate"}:
            if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
                raise TypeError("Mongo workflow result must be documents")
            expected_count = len(payload)
        elif command.operation == "count":
            if not isinstance(payload, int) or isinstance(payload, bool) or payload < 0:
                raise TypeError("Mongo count result must be a nonnegative integer")
            expected_count = 1
        else:
            if not isinstance(payload, dict) or not isinstance(payload.get("values"), list):
                raise TypeError("Mongo distinct result must contain a values array")
            expected_count = 1
        if not isinstance(count, int) or isinstance(count, bool) or count != expected_count:
            raise ValueError("Mongo workflow rowCount must match the service result")
        if not isinstance(result.get("truncated"), bool):
            raise TypeError("Mongo workflow read result requires a truncation flag")
        self.failures.pop(db_id, None)
        self.read_counts[db_id] = self.read_counts.get(db_id, 0) + 1
        return True

    def status(self) -> str | None:
        if self.failures:
            return "Mongo workflow read failed: " + "; ".join(self.failures.values())
        if self.database_ids and not self.read_counts:
            return "No MongoDB read command succeeded. Workflow is incomplete or unverified."
        return None
