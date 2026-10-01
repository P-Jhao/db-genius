"""File import evidence from authorized service results, never model previews."""

from dataclasses import dataclass, field

from app.agent.workflow_rows import (
    Row,
    covers,
    expression,
    insert_values,
    is_insert,
    is_select,
    merge_observations,
    ordered_page,
    rows,
    tables,
    verifies_columns,
    write_tables,
)
from app.agent.workflow_schema import Target, WorkflowSchema
from app.core.errors import BusinessError


@dataclass
class WorkflowProgress:
    attached_files: set[int]
    schema: WorkflowSchema = field(default_factory=WorkflowSchema)
    read_files: set[int] = field(default_factory=set)
    source_rows_by_file: dict[int, list[Row]] = field(default_factory=dict)
    headers_by_file: dict[int, list[str]] = field(default_factory=dict)
    expected_rows_by_file: dict[int, int] = field(default_factory=dict)
    inserted_rows: int = 0
    inserted_values: dict[Target, list[Row]] = field(default_factory=dict)
    selected_values: dict[Target, list[Row]] = field(default_factory=dict)
    selected_pages: dict[Target, dict[str, dict[tuple[int, int], list[Row]]]] = field(default_factory=dict)
    successful_tools: int = 0
    source_truncated: bool = False
    written_databases: set[int] = field(default_factory=set)
    pending_verification: set[Target] = field(default_factory=set)
    sql_failures: dict[tuple[int, bool], str] = field(default_factory=dict)
    failure: str | None = None

    def before_call(self, name: str, args: dict[str, object]) -> None:
        if self.failure is not None:
            raise RuntimeError("Workflow stopped after a failed tool")
        if name != "executeSql" or not self.attached_files:
            return
        statement = args.get("statement")
        if not isinstance(statement, str):
            raise TypeError("SQL statement must be text")
        db_id = args.get("db_id")
        if not isinstance(db_id, int):
            raise TypeError("SQL database ID must be an integer")
        if not is_select(statement, self.schema.dialects.get(db_id)) and not self.read_files:
            raise BusinessError(400, "Read an attached file before writing import data")

    def after_call(self, name: str, args: dict[str, object], result: object) -> None:
        if name == "getDatabaseSchema":
            db_id = args.get("db_id")
            if not isinstance(db_id, int):
                raise TypeError("Schema database ID must be an integer")
            self.schema.register(db_id, result)
            self.successful_tools += 1
            return
        if name not in ("readFile", "readImage", "executeSql"):
            return
        if not isinstance(result, dict):
            raise TypeError("Workflow service result must be an object")
        if "marker" in result:
            raise ValueError("Workflow evidence must use the full service result")
        if result.get("success") is not True:
            error = result.get("error")
            diagnostic = f"{name} did not succeed" + (f": {error}" if isinstance(error, str) else "")
            if name == "executeSql":
                db_id, statement = args.get("db_id"), args.get("statement")
                if not isinstance(db_id, int) or not isinstance(statement, str):
                    raise TypeError("SQL tool arguments are invalid")
                self.sql_failures[(db_id, is_select(statement, self.schema.dialects.get(db_id)))] = diagnostic
            else:
                self.failure = diagnostic
            return
        self.successful_tools += 1
        if name in ("readFile", "readImage"):
            file_id = args.get("file_id")
            if not isinstance(file_id, int) or file_id not in self.attached_files:
                raise ValueError("Workflow file was not attached")
            self.read_files.add(file_id)
            self.source_truncated |= result.get("truncated") is True
            total = result.get("totalRows")
            if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
                self.expected_rows_by_file[file_id] = total
            if "data" in result:
                self.source_rows_by_file[file_id] = rows(result["data"])
            headers = result.get("headers")
            if isinstance(headers, list) and all(isinstance(item, str) for item in headers):
                self.headers_by_file[file_id] = headers
            return
        db_id, statement = args.get("db_id"), args.get("statement")
        if not isinstance(db_id, int) or not isinstance(statement, str):
            raise TypeError("SQL tool arguments are invalid")
        dialect = self.schema.dialects.get(db_id)
        selecting = is_select(statement, dialect)
        referenced = tables(statement, dialect) if selecting else write_tables(statement, dialect)
        selected_tables = {self.schema.table_name(db_id, table) for table in referenced}
        self.sql_failures.pop((db_id, selecting), None)
        if selecting:
            selected = rows(result.get("data"), dialect)
            # Each returned row is real even when the adapter stopped at its 100-row cap.
            # Subsequent distinct SELECTs can cover the remainder; repeats do not add copies.
            for table in selected_tables:
                target = (db_id, table)
                if target not in self.pending_verification:
                    continue
                expected = self.inserted_values.get(target, [])
                if not self.source_rows_by_file and not expected:
                    if result.get("truncated") is not True:
                        self.pending_verification.discard(target)
                    continue
                if len(selected_tables) != 1:
                    continue
                if not expected:
                    continue
                if not verifies_columns(statement, set(expected[0]), dialect):
                    continue
                column_types = self.schema.column_types.get(target, {})
                projected = [{column: row[column] for column in expected[0] if column in row}
                             for row in selected]
                accumulated = merge_observations(self.selected_values.get(target, []), projected, column_types)
                page = ordered_page(statement, set(expected[0]), len(projected), dialect)
                if page is not None:
                    family, start, end = page
                    windows = self.selected_pages.setdefault(target, {}).setdefault(family, {})
                    if not any(start < stop and end > begin for begin, stop in windows):
                        windows[(start, end)] = projected
                    accumulated = merge_observations(
                        accumulated, [row for batch in windows.values() for row in batch], column_types,
                    )
                self.selected_values[target] = accumulated
                if covers(expected, accumulated, column_types):
                    self.pending_verification.discard(target)
        elif "affectedRows" in result:
            self.written_databases.add(db_id)
            self.schema.created_table(db_id, expression(statement, dialect))
            headers = next(iter(self.headers_by_file.values()), []) if len(self.headers_by_file) == 1 else []
            values = insert_values(statement, headers, dialect)
            affected = result["affectedRows"]
            for table in selected_tables:
                target = (db_id, table)
                self.pending_verification.add(target)
                self.selected_values.pop(target, None)
                self.selected_pages.pop(target, None)
                if values and affected == len(values):
                    self.inserted_values.setdefault(target, []).extend(values)
                else:
                    self.inserted_values.pop(target, None)
            if is_insert(statement, dialect) and isinstance(affected, int) and affected > 0:
                self.inserted_rows += affected

    def status(self) -> str | None:
        reasons: list[str] = []
        if self.failure is not None:
            reasons.append(self.failure)
        reasons.extend(self.sql_failures.values())
        if not self.attached_files and self.successful_tools == 0:
            reasons.append("No workflow tool succeeded")
        if self.attached_files - self.read_files:
            reasons.append("Not all attached files were successfully read")
        if self.attached_files and not self.written_databases:
            reasons.append("No database write was confirmed")
        expected_rows = sum(self.expected_rows_by_file.values())
        if expected_rows > self.inserted_rows:
            reasons.append(f"Only {self.inserted_rows} of {expected_rows} source rows were inserted")
        source = [row for file_rows in self.source_rows_by_file.values() for row in file_rows]
        if expected_rows != len(source):
            reasons.append("Not all source rows were available from the parser")
        remaining = [(target, row) for target, batch in self.inserted_values.items() for row in batch]
        covered = True
        for row in source:
            match = next((index for index, (target, candidate) in enumerate(remaining)
                          if covers(rows([row], self.schema.dialects.get(target[0])), [candidate],
                                    self.schema.column_types.get(target, {}))), None)
            if match is None:
                covered = False
                break
            remaining.pop(match)
        if not covered:
            reasons.append("Confirmed inserts do not cover the source rows")
        if self.pending_verification:
            reasons.append("Database writes lack a successful subsequent SELECT matching source rows")
        if self.source_truncated:
            reasons.append("A file read result was truncated; only a partial import can be claimed")
        if not reasons:
            return None
        return "; ".join(reasons) + ". Workflow is incomplete or unverified."
