"""Read-only MongoDB adapter with bounded results and sampled metadata."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from bson import Code, Decimal128, Int64, ObjectId, json_util
from pymongo import MongoClient
from pymongo.errors import ExecutionTimeout, NetworkTimeout, OperationFailure, PyMongoError

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.adapters.diagnostics import sanitize_diagnostic
from app.adapters.document import render_document
from app.adapters.mongodb_command import MongoCommand, UnsafeMongoCommand, parse_command
from app.adapters.mongodb_metadata import read_collection
from app.adapters.types import (
    DbConnectionConfig,
    QueryResult,
    SchemaMetadata,
)


def _bson_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, ObjectId):
        return "objectId"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, Code):
        return "javascript" if value.scope is None else "javascript_with_scope"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Int64):
        return "long"
    if isinstance(value, int):
        return "int" if -(2**31) <= value < 2**31 else "long"
    if isinstance(value, float):
        return "double"
    if isinstance(value, (Decimal128, Decimal)):
        return "decimal"
    if isinstance(value, datetime):
        return "date"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, bytes):
        return "binData"
    return type(value).__name__.lower()


def _json_document(value: object) -> dict[str, object]:
    encoded: object = json.loads(json_util.dumps(value))
    if not isinstance(encoded, dict) or not all(isinstance(key, str) for key in encoded):
        raise TypeError("MongoDB document is not a JSON object")
    return cast(dict[str, object], encoded)


def _bson_input(value: object) -> object:
    # Document.parse in the Java adapter accepts Extended JSON values such as $oid.
    return json_util.loads(json.dumps(value))


def _interrupt_reason(cancel_event: threading.Event | None) -> Literal["cancelled", "timeout"]:
    if cancel_event is not None and cancel_event.is_set():
        return "cancelled"
    return "timeout"


class MongoDbAdapter:
    db_type = "mongodb"

    def validate_config(self, config: DbConnectionConfig) -> None:
        if config.db_type != self.db_type:
            raise ValueError("Expected database type mongodb")
        if not isinstance(config.host, str) or not config.host.strip():
            raise ValueError("host is required")
        if not isinstance(config.db_name, str) or not config.db_name.strip():
            raise ValueError("db_name is required")
        if not isinstance(config.port, int) or isinstance(config.port, bool) or not 1 <= config.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not isinstance(config.username, str) or not isinstance(config.password, str):
            raise TypeError("MongoDB credentials must be strings")
        if bool(config.username.strip()) != bool(config.password.strip()):
            raise ValueError("MongoDB username and password must both be present or both be empty")

    def _client(self, config: DbConnectionConfig, timeout_seconds: int) -> MongoClient[dict[str, object]]:
        self.validate_config(config)
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if config.username.strip():
            return MongoClient(config.host, config.port, username=config.username.strip(),
                               password=config.password,
                               serverSelectionTimeoutMS=min(timeout_seconds, 10) * 1000,
                               connectTimeoutMS=min(timeout_seconds, 10) * 1000,
                               socketTimeoutMS=timeout_seconds * 1000)
        return MongoClient(config.host, config.port,
                           serverSelectionTimeoutMS=min(timeout_seconds, 10) * 1000,
                           connectTimeoutMS=min(timeout_seconds, 10) * 1000,
                           socketTimeoutMS=timeout_seconds * 1000)

    def test_connection(self, config: DbConnectionConfig) -> bool:
        try:
            with self._client(config, 5) as client:
                result = client[config.db_name].command("ping")
                return result.get("ok") == 1
        except PyMongoError:
            return False

    def is_read_only(self, statement: str) -> bool:
        try:
            parse_command(statement)
            return True
        except (UnsafeMongoCommand, TypeError):
            return False

    def extract_metadata(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> SchemaMetadata:
        metadata: SchemaMetadata = {
            "dbType": self.db_type, "databaseName": config.db_name, "host": config.host,
            "port": config.port, "tables": [], "incomplete": False, "errorMessage": None,
            "schemaInferred": True, "sampleSize": 50,
        }
        errors: list[str] = []
        max_time_ms = timeout_seconds * 1000
        try:
            with self._client(config, timeout_seconds) as client:
                database = client[config.db_name]
                for name in database.list_collection_names(maxTimeMS=max_time_ms):
                    table, failures = read_collection(name, database[name], max_time_ms, _bson_type)
                    metadata["tables"].append(table)
                    errors.extend(sanitize_diagnostic(error, config) for error in failures)
        except PyMongoError as exc:
            errors.append(sanitize_diagnostic(str(exc), config))
        if errors:
            metadata["incomplete"] = True
            metadata["errorMessage"] = "; ".join(errors)
        return metadata

    def generate_document(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> str:
        return render_document(self.extract_metadata(config, timeout_seconds=timeout_seconds))

    def _run(self, client: MongoClient[dict[str, object]], config: DbConnectionConfig,
             command: MongoCommand, max_rows: int, max_time_ms: int) -> QueryResult:
        collection = client[config.db_name][command.collection]
        filters = cast(dict[str, object], _bson_input(command.filter))
        if command.operation == "find":
            cursor = collection.find(filters).limit(min(command.limit, max_rows) + 1)
            documents = list(cursor.max_time_ms(max_time_ms))
            selected = documents[:min(command.limit, max_rows)]
            data = [_json_document(item) for item in selected]
            return {"success": True, "rowCount": len(data), "result": data,
                    "truncated": len(documents) > len(selected)}
        if command.operation == "aggregate":
            stages = cast(list[dict[str, object]], _bson_input(command.pipeline))
            pipeline: list[dict[str, object]] = [*stages,
                                                 {"$limit": min(command.limit, max_rows) + 1}]
            documents = list(collection.aggregate(pipeline, maxTimeMS=max_time_ms))
            selected = documents[:min(command.limit, max_rows)]
            data = [_json_document(item) for item in selected]
            return {"success": True, "rowCount": len(data), "result": data,
                    "truncated": len(documents) > len(selected)}
        if command.operation == "count":
            count = collection.count_documents(filters, maxTimeMS=max_time_ms)
            return {"success": True, "rowCount": 1, "result": count, "truncated": False}
        if command.operation == "distinct" and command.field is not None:
            values = collection.distinct(command.field, filters, maxTimeMS=max_time_ms)
            selected = values[:max_rows]
            result = _json_document({"values": selected})
            return {"success": True, "rowCount": 1, "result": result,
                    "truncated": len(values) > max_rows}
        raise RuntimeError("Unreachable MongoDB operation")

    def execute(self, config: DbConnectionConfig, statement: str, *, trial_mode: bool = False,
                timeout_seconds: int = 30, max_rows: int = 100,
                cancel_event: threading.Event | None = None) -> QueryResult:
        command = parse_command(statement)
        if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows <= 0:
            raise ValueError("max_rows must be positive")
        if cancel_event is not None and cancel_event.is_set():
            raise DatabaseExecutionInterrupted("cancelled", cancel_request_sent=False,
                                               server_termination_confirmed=False,
                                               write_outcome_unknown=False)
        try:
            with self._client(config, timeout_seconds) as client:
                result = self._run(client, config, command, min(max_rows, 100), timeout_seconds * 1000)
        except ExecutionTimeout as exc:
            reason = _interrupt_reason(cancel_event)
            raise DatabaseExecutionInterrupted(reason, cancel_request_sent=False,
                                               server_termination_confirmed=True,
                                               write_outcome_unknown=False) from exc
        except NetworkTimeout as exc:
            reason = _interrupt_reason(cancel_event)
            raise DatabaseExecutionInterrupted(reason, cancel_request_sent=False,
                                               server_termination_confirmed=False,
                                               write_outcome_unknown=False) from exc
        except PyMongoError as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise DatabaseExecutionInterrupted("cancelled", cancel_request_sent=False,
                                                   server_termination_confirmed=False,
                                                   write_outcome_unknown=False) from exc
            if isinstance(exc, OperationFailure) and exc.code in {2, 9, 14, 168}:
                details = exc.details
                if not isinstance(details, dict) or not isinstance(details.get("errmsg"), str):
                    raise TypeError("Mongo query diagnostic requires a server error message") from exc
                message = sanitize_diagnostic(details["errmsg"], config)
                return {"success": False, "error": message[:1000], "errorCode": exc.code}
            raise
        if cancel_event is not None and cancel_event.is_set():
            raise DatabaseExecutionInterrupted("cancelled", cancel_request_sent=False,
                                               server_termination_confirmed=False,
                                               write_outcome_unknown=False)
        return result
