"""Track metadata actually delivered to the model, including full artifact paging."""

import json
from dataclasses import dataclass, field

from app.agent.task_goal import TaskGoal


@dataclass
class SchemaObservation:
    result: object
    delivered: bool
    artifact_id: str | None = None
    pages: dict[int, str] = field(default_factory=dict)


@dataclass
class SchemaEvidence:
    observations: dict[int, SchemaObservation] = field(default_factory=dict)

    def register(self, db_id: int, result: object, output: str) -> None:
        visible: object = json.loads(output)
        artifact_id = visible.get("artifactId") if isinstance(visible, dict) else None
        if artifact_id is not None and not isinstance(artifact_id, str):
            raise TypeError("Schema artifact identity must be text")
        self.observations[db_id] = SchemaObservation(result, artifact_id is None, artifact_id)

    def observe_page(self, artifact_id: str, page: object) -> None:
        matches = [value for value in self.observations.values() if value.artifact_id == artifact_id]
        if not matches:
            return
        if not isinstance(page, dict):
            raise TypeError("Schema artifact page must be an object")
        offset, content = page.get("offset"), page.get("content")
        total, next_offset = page.get("totalCharacters"), page.get("nextOffset")
        if (type(offset) is not int or not isinstance(content, str) or type(total) is not int
                or type(next_offset) is not int or next_offset != offset + len(content)):
            raise TypeError("Schema artifact page coordinates are invalid")
        for observation in matches:
            observation.pages[offset] = content
            chunks: list[str] = []
            position = 0
            while position in observation.pages:
                chunk = observation.pages[position]
                if not chunk:
                    break
                chunks.append(chunk)
                position += len(chunk)
            if position == total:
                if json.loads("".join(chunks)) != observation.result:
                    raise ValueError("Paged metadata differs from its registered schema")
                observation.delivered = True

    def status(self, goal: TaskGoal) -> dict[str, object]:
        databases: list[dict[str, object]] = []
        for scope in goal.tableScope:
            observation = self.observations.get(scope.dbId)
            reason: str | None = None
            known_null: list[str] = []
            omitted: list[str] = []
            observed_names: list[str] = []
            if observation is None:
                reason = "schema_not_read"
            elif not observation.delivered:
                reason = "schema_output_truncated"
            if observation is not None and observation.delivered:
                result = observation.result
                if not isinstance(result, dict):
                    reason = "schema_unavailable"
                else:
                    tables = result.get("tables")
                    if not isinstance(tables, list):
                        reason = "table_inventory_missing"
                    else:
                        for table in tables:
                            if not isinstance(table, dict) or not isinstance(table.get("name"), str):
                                reason = "table_inventory_partial"
                                continue
                            name = table["name"]
                            observed_names.append(name)
                            if scope.tables is not None and name not in scope.tables:
                                continue
                            if not isinstance(table.get("columns"), list):
                                reason = "column_inventory_missing"
                            self._attributes(table, name, known_null, omitted)
                            for column in table.get("columns", []) if isinstance(table.get("columns"), list) else []:
                                if isinstance(column, dict) and isinstance(column.get("name"), str):
                                    self._attributes(column, name + "." + column["name"], known_null, omitted)
                                    if not isinstance(column.get("type"), str) or type(column.get("nullable")) is not bool:
                                        reason = "column_attributes_missing"
                                else:
                                    reason = "column_inventory_partial"
                    if (result.get("incomplete") is not False or result.get("truncated") is True
                            or result.get("errorMessage") not in (None, "")):
                        reason = "source_schema_partial"
                    if scope.tables is not None and not set(scope.tables).issubset(observed_names):
                        reason = "requested_tables_not_observed"
            databases.append({"dbId": scope.dbId, "tables": scope.tables,
                              "observedTables": observed_names, "complete": reason is None,
                              "missingTables": [] if scope.tables is None else
                                  [name for name in scope.tables if name not in observed_names],
                              "limitation": reason, "knownNullAttributes": known_null,
                              "omittedAttributes": omitted})
        return {"complete": bool(databases) and all(db["complete"] is True for db in databases),
                "databases": databases}

    @staticmethod
    def _attributes(value: dict[str, object], prefix: str, known_null: list[str],
                    omitted: list[str]) -> None:
        for attribute in ("comment", "type", "nullable", "defaultValue"):
            path = prefix + "." + attribute
            if attribute not in value:
                omitted.append(path)
            elif value[attribute] is None:
                known_null.append(path)
