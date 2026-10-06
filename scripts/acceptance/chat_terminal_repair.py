"""Opt-in local MySQL chat acceptance; reports contain counts and flags, never message text."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / ".git/acceptance/chat-terminal-repair"


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Expected an object")
    return value


def api(client: httpx.Client, method: str, path: str, body: object = None) -> object:
    response = client.request(method, path, json=body)
    response.raise_for_status()
    packet = object_value(response.json())
    if packet.get("code") != 200:
        raise RuntimeError("API prerequisite failed")
    return packet.get("data")


def independent_schema(container: str, database_id: int) -> dict[str, object]:
    script = """
import json,sys
from app.core.database import SessionLocal
from app.models import DbConfig
from app.services.database_tools import get_schema
with SessionLocal() as session:
    config=session.get(DbConfig,int(sys.argv[1]))
    if config is None or config.db_type != 'mysql' or config.status != 1:
        raise RuntimeError('Expected healthy MySQL config')
    owner=config.user_id
schema=get_schema(owner,int(sys.argv[1]))
if schema.get('incomplete') is not False or schema.get('errorMessage') is not None:
    raise RuntimeError('Independent schema is incomplete')
names=[table['name'] for table in schema['tables']]
print(json.dumps({'dbType':schema['dbType'],'tableNames':names,
                  'schemaCharacters':len(json.dumps(schema,ensure_ascii=False))}))
"""
    result = subprocess.run(["docker", "exec", container, "python", "deploy/connection_env.py",
                             "python", "-c", script, str(database_id)],
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode != 0:
        raise RuntimeError("Independent Docker MySQL schema check failed")
    evidence = object_value(json.loads(result.stdout))
    names = evidence.get("tableNames")
    if evidence.get("dbType") != "mysql" or not isinstance(names, list) or len(names) != 10:
        raise ValueError("Acceptance requires an independently verified ten-table MySQL schema")
    if not all(isinstance(name, str) and name for name in names):
        raise TypeError("Independent table names must be text")
    return evidence


def chat(client: httpx.Client, body: dict[str, object]) -> list[dict[str, object]]:
    events = []
    with client.stream("POST", "chat", json=body) as response:
        response.raise_for_status()
        if not response.headers.get("content-type", "").startswith("text/event-stream"):
            raise RuntimeError("Expected SSE response")
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(object_value(json.loads(line.removeprefix("data:"))))
    if not events:
        raise RuntimeError("Empty SSE response")
    return events


def conversation(events: list[dict[str, object]]) -> int:
    values = [row["content"] for row in events if row["type"] == "conversation"]
    if len(values) != 1 or type(values[0]) is not int:
        raise TypeError("Expected one conversation ID")
    return values[0]


def replay(values: list[dict[str, object]]) -> list[tuple[str, object, str]]:
    """Normalize adjacent blocks because public SSE has no model-call identity."""
    blocks: list[tuple[str, object, str]] = []
    for row in values:
        kind, content = row["type"], row["content"]
        if kind not in {"reasoning", "step"}:
            continue
        if not isinstance(content, str):
            raise TypeError("Replay content must be text")
        if not content:
            continue
        if kind == "reasoning" and blocks and blocks[-1][:2] == (kind, row.get("step")):
            previous = blocks[-1]
            blocks[-1] = (previous[0], previous[1], previous[2] + content)
        else:
            blocks.append((str(kind), row.get("step"), content))
    return blocks


def judge(events: list[dict[str, object]], rows: list[dict[str, object]], names: list[str]) -> dict[str, object]:
    kinds = [event["type"] for event in events]
    finals = [event["content"] for event in events if event["type"] == "summary"]
    stored = [row["content"] for row in rows if row["type"] == "summary"]
    final = finals[0] if len(finals) == 1 else ""
    if not isinstance(final, str):
        raise TypeError("Summary must be text")
    delta = "".join(str(event["content"]) for event in events if event["type"] == "summary_delta")
    usage = [object_value(event["content"]) for event in events if event["type"] == "usage"]
    reasoning = [row for row in rows if row["type"] == "reasoning"]
    steps = [str(event["content"]) for event in events if event["type"] == "step"]
    checks = {
        "oneSummary": len(finals) == len(stored) == 1,
        "historyMatches": stored == finals,
        "summaryDeltasMatch": delta == final,
        "tablesMatchIndependentSchema": all(name in final for name in names),
        "zeroExecutionFailureAbsent": "没有成功执行任何数据库语句" not in final,
        "noStatementExecution": not any(step.startswith("executeSql:") for step in steps),
        "noErrorOrClarify": not any(kind in {"error", "clarify"} for kind in kinds),
        "oneUsageAndDone": kinds.count("usage") == kinds.count("done") == 1 and kinds[-1] == "done",
        "replayOrderMatches": replay(events) == replay(rows),
        "reasoningBeforeSummary": bool(rows) and rows[-1]["type"] == "summary",
        "noDuplicateReasoningFields": all(row.get("reasoningContent") is None for row in rows),
    }
    return {"passed": all(checks.values()), **checks, "eventTypeCounts": dict(Counter(kinds)),
            "reasoningObserved": bool(reasoning), "reasoningBlocks": len(reasoning),
            "matchedTableCount": sum(name in final for name in names), "independentTableCount": len(names),
            "summaryCharacters": len(final),
            "toolPages": sum(step.startswith("readToolOutput:") for step in steps),
            "modelCallCount": usage[0].get("callCount") if len(usage) == 1 else None}


def run(options: argparse.Namespace, persist_path: Path) -> dict[str, object]:
    credentials = options.credentials.resolve()
    if not credentials.is_relative_to(ROOT) or subprocess.run(
        ["git", "check-ignore", "--quiet", str(credentials)], cwd=ROOT, check=False).returncode != 0:
        raise ValueError("Credentials must come from an ignored workspace env file")
    values = dotenv_values(credentials, interpolate=False)
    username, password = values.get("SQLCHAT_BOOTSTRAP_USERNAME"), values.get("SQLCHAT_BOOTSTRAP_PASSWORD")
    if not username or not password:
        raise ValueError("Ignored env must provide bootstrap login credentials")
    parsed = urlsplit(options.base_url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.scheme != "http":
        raise ValueError("Acceptance targets only the local HTTP deployment")
    report: dict[str, object] = {"scope": "chat-terminal-repair-mysql", "model": "deepseek-flash", "cases": []}
    cases: list[dict[str, object]] = []

    def save() -> None:
        report["cases"] = cases
        persist_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with httpx.Client(base_url=options.base_url.rstrip("/") + "/api/",
                      timeout=httpx.Timeout(330, connect=10), headers={"Accept-Language": "zh-CN"}) as client:
        login = object_value(api(client, "POST", "auth/login", {"username": username, "password": password}))
        token = login.get("token")
        if not isinstance(token, str) or not token:
            raise TypeError("Login token is missing")
        client.headers["Authorization"] = token
        try:
            selected = object_value(api(client, "GET", f"db-config/{options.database_id}"))
            if selected.get("status") != 1 or selected.get("dbType") not in {"mysql", "*"}:
                raise ValueError("Selected configuration must be healthy MySQL or masked trial configuration")
            active = object_value(api(client, "GET", "model-config/active"))
            if active.get("modelName") != "deepseek-flash":
                raise ValueError("Existing active model must be deepseek-flash")
            evidence = independent_schema(options.api_container, options.database_id)
            names = evidence["tableNames"]
            if not isinstance(names, list):
                raise TypeError("Expected independent schema names")
            report.update({"databaseId": options.database_id, "independentTableCount": len(names),
                           "schemaCharacters": evidence["schemaCharacters"]})
            missing = chat(client, {"message": "有哪些表？", "confirmedIntent": "sql_query"})
            missing_kinds = [event["type"] for event in missing]
            missing_history = api(client, "GET", f"chat/conversations/{conversation(missing)}/messages")
            if not isinstance(missing_history, list):
                raise TypeError("Expected missing-resource history")
            missing_rows = [object_value(row) for row in missing_history]
            missing_errors = [event["content"] for event in missing if event["type"] == "error"]
            missing_usage = [object_value(event["content"]) for event in missing if event["type"] == "usage"]
            missing_checks = {
                "exactLocalizedError": missing_errors == ["SQL 查询需要至少选择一个数据库配置"],
                "noRepeatedClarification": "clarify" not in missing_kinds
                    and not any(row["type"] == "clarify" for row in missing_rows),
                "oneUsageAndDone": missing_kinds.count("usage") == missing_kinds.count("done") == 1
                    and missing_kinds[-1] == "done",
                "zeroModelCalls": len(missing_usage) == 1 and missing_usage[0].get("callCount") == 0,
                "storedErrorMatches": [row["content"] for row in missing_rows
                    if row["type"] == "error"] == missing_errors,
                "noDatabaseOrReasoning": "reasoning" not in missing_kinds and "step" not in missing_kinds,
            }
            case = {"case": "confirmed_sql_missing_database", "eventTypeCounts": dict(Counter(missing_kinds)),
                    "passed": all(missing_checks.values()), **missing_checks}
            cases.append(case)
            save()
            first = chat(client, {"message": "你能做什么？", "confirmedIntent": "simple_chat"})
            first_kinds = [event["type"] for event in first]
            cases.append({"case": "prior_simple_chat", "eventTypeCounts": dict(Counter(first_kinds)),
                          "passed": "content" in first_kinds and "error" not in first_kinds
                              and "clarify" not in first_kinds and first_kinds[-1] == "done"})
            conversation_id = conversation(first)
            report["conversationId"] = conversation_id
            initial = api(client, "GET", f"chat/conversations/{conversation_id}/messages")
            if not isinstance(initial, list):
                raise TypeError("Expected stored history")
            prior = len(initial)
            for index, question in enumerate(("有哪些表", "有哪些表？"), start=1):
                body: dict[str, object] = {"message": question,
                    "conversationId": conversation_id, "dbConfigIds": [options.database_id]}
                if index == 1:
                    body["confirmedIntent"] = "sql_query"
                events = chat(client, body)
                if conversation(events) != conversation_id:
                    raise ValueError("Follow-up must preserve conversation identity")
                stored = api(client, "GET", f"chat/conversations/{conversation_id}/messages")
                if not isinstance(stored, list):
                    raise TypeError("Expected stored history")
                rows = [object_value(row) for row in stored[prior:]]
                prior = len(stored)
                cases.append({"case": f"table_list_turn_{index}", **judge(events, rows, names)})
                save()
            report["passed"] = all(case["passed"] is True for case in cases)
            save()
        finally:
            api(client, "POST", "auth/logout")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8109")
    parser.add_argument("--credentials", type=Path, default=ROOT / ".env")
    parser.add_argument("--database-id", type=int, default=2)
    parser.add_argument("--api-container", default="sqlchat-api-1")
    options = parser.parse_args()
    if options.database_id < 1:
        raise ValueError("Database identity must be positive")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    destination = DESTINATION / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    try:
        report = run(options, destination)
        print(json.dumps({"passed": report["passed"], "evidence": str(destination)}))
        return 0 if report["passed"] is True else 1
    except Exception as error:  # noqa: BLE001 - never expose credential-bearing exception messages
        print(json.dumps({"passed": False, "errorType": type(error).__name__, "evidence": str(destination)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
