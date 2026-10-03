"""Opt-in Python classifier effects with complete, reviewable turn evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from real_model_api import ApiSession, api_session
from real_model_cases import EffectCase, QueryOracle
from real_model_database import TargetSnapshot, isolated_database
from real_model_evidence import _history_checks, tool_results
from real_model_oracles import database_rows_match, query_matches
from real_model_regression_support import options, report_run
from real_model_relay import RealProviderRelay, object_value
from real_model_report import application_usage, provider_summary
from real_model_runner import _conversation, _finished_calls
from real_model_synthetic_evidence import executed_sql, scrub, turn_evidence
from sqlalchemy import inspect

SCOPE = "python-only-classification-regression"
REPETITIONS = 3
CaseKind = Literal["sql", "chat", "workflow", "history", "ambiguous_db", "ambiguous_file"]
COUNT_ALL = QueryOracle("SELECT COUNT(*) AS order_count FROM orders", ((6,),), ("order_count",))
COUNT_PAID = QueryOracle("SELECT COUNT(*) AS order_count FROM orders WHERE status='paid'", ((5,),), ("order_count",))
EMPTY_CONTACTS = QueryOracle("SELECT COUNT(*) AS initial_count FROM imported_contacts", ((0,),), ("initial_count",))
CONTACTS = QueryOracle("SELECT id,name,city FROM imported_contacts ORDER BY id",
                       ((201, "Iris", "杭州"), (202, "Owen", "深圳")), ("id", "name", "city"))


@dataclass(frozen=True)
class Case:
    code: CaseKind
    questions: tuple[str, ...]
    expected_intent: str | None
    oracles: tuple[tuple[QueryOracle, ...], ...]
    clarify: bool = False
    attachment: bool = False

    def effect(self) -> EffectCase:
        return EffectCase(self.code, self.questions, None, self.oracles, expects_clarification=self.clarify)


CASES = (
    Case("sql", ("查询 orders 表的总行数，返回 order_count 一列。",), "sql_query", ((COUNT_ALL,),)),
    Case("chat", ("你好，请简单介绍你自己。",), "simple_chat", ((),)),
    Case("workflow", ((
        "执行完整批处理流程：第一阶段核验 imported_contacts 表结构，并执行 COUNT(*) 返回 initial_count；"
        "第二阶段把下列两条记录"
        "分成两个独立 INSERT 批次写入该表，每个批次一条：(201,'Iris','杭州')、(202,'Owen','深圳')；"
        "第三阶段 SELECT id,name,city ORDER BY id，逐行核对两条来源记录并报告验证结果。"
        "不使用附件，不改变表结构或其他表。"),), "workflow", ((EMPTY_CONTACTS, CONTACTS),)),
    Case("history", ("查询 orders 表总行数，返回 order_count 一列。",
                     "同一张表只统计 status='paid' 的行，仍返回 order_count 一列。"), "sql_query",
         ((COUNT_ALL,), (COUNT_PAID,))),
    Case("ambiguous_db", ("处理一下这些数据。",), None, ((),), clarify=True),
    Case("ambiguous_file", ("处理一下附件数据。",), None, ((),), clarify=True, attachment=True),
)


def _classification(events: list[dict[str, object]]) -> dict[str, object]:
    values = [event.get("content") for event in events if event.get("type") == "classified"]
    if len(values) != 1:
        raise ValueError("Expected exactly one classifier event")
    value = object_value(values[0])
    if set(value) != {"intent", "confidence", "reasoning", "needsClarification"}:
        raise ValueError("Classifier contract changed")
    return value


def _shape(target: TargetSnapshot) -> list[dict[str, object]]:
    return [{"name": row["name"], "type": str(row["type"]), "nullable": row["nullable"]}
            for row in inspect(target.engine).get_columns("imported_contacts")]


def _turn(case: Case, index: int, repetition: int, session: ApiSession, target: TargetSnapshot,
          relay: RealProviderRelay, db_id: int, conversation_id: int | None,
          file_id: int | None) -> tuple[dict[str, object], int | None]:
    question = case.questions[index]
    label = f"{SCOPE}/{case.code}/{repetition}/{index + 1}"
    offset = relay.begin(label)
    session.event_capture = []
    secrets = (relay.upstream_key.get_secret_value(), relay.access_key.get_secret_value(),
               session.token.get_secret_value(), target.password.get_secret_value())
    row: dict[str, object] = {"turn": index + 1, "status": "failed", "stage": "fingerprint"}
    try:
        excluded = ("imported_contacts",) if case.code == "workflow" else ()
        before, shape = target.fingerprint(exclude_tables=excluded), _shape(target)
        row["beforeFingerprint"] = before
        initial_contacts = (database_rows_match(EMPTY_CONTACTS, target.rows(EMPTY_CONTACTS.statement))
                            if case.code == "workflow" else True)
        body: dict[str, object] = {"message": question, "dbConfigIds": [db_id]}
        if conversation_id is not None:
            body["conversationId"] = conversation_id
        if file_id is not None:
            body["fileIds"] = [file_id]
        row["stage"] = "chat"
        events, timing = session.chat(body)
        row["timing"] = timing
        current_id = _conversation(events)
        if conversation_id is not None and current_id != conversation_id:
            raise ValueError("Follow-up did not reuse its conversation")
        conversation_id = current_id
        row["stage"] = "history"
        history = session.messages(current_id) if current_id is not None else []
        row["historyMessageCount"] = len(history)
        observed = _classification(events)
        tools = tool_results(events)
        oracles = case.oracles[index]
        row["stage"] = "oracle"
        after = target.fingerprint(exclude_tables=excluded)
        row["afterFingerprint"] = after
        checks: dict[str, object] = {
            "classifierIntent": case.expected_intent is None or observed["intent"] == case.expected_intent,
            "classifierClarification": observed["needsClarification"] is case.clarify,
            "historyReplay": _history_checks(events, history, question, case.clarify),
            "historySequence": [item.get("content") for item in history if item.get("role") == "user"]
                               == list(case.questions[:index + 1]),
            "noUnexpectedDataChange": after == before and _shape(target) == shape,
            "queryResult": all(any(result.name == "executeSql" and isinstance(result.value, dict)
                                   and result.value.get("success") is True
                                   and query_matches(oracle, result.value.get("data")) for result in tools)
                               for oracle in oracles),
            "independentDatabaseResults": initial_contacts and all(
                database_rows_match(oracle, target.rows(oracle.statement))
                for oracle in oracles if case.code != "workflow" or oracle != EMPTY_CONTACTS),
            "toolBehavior": not tools if case.clarify or case.code == "chat" else bool(tools),
            "clarificationEvent": any(event.get("type") == "clarify" for event in events) is case.clarify,
        }
        if case.code == "workflow":
            checks["separateVerifiedBatches"] = len([result for result in tools if result.name == "executeSql"
                and isinstance(result.value, dict) and result.value.get("success") is True
                and result.value.get("affectedRows") == 1]) == 2
        elif case.code not in {"chat", "ambiguous_db", "ambiguous_file"}:
            checks["noSuccessfulWrite"] = not any(isinstance(result.value, dict) and "affectedRows" in result.value
                                                 and result.value.get("success") is True for result in tools)
        if case.clarify:
            checks["noExecutionPreparation"] = not any(event.get("type") in {
                "routing", "thinking", "step", "content", "summary", "summary_delta"} for event in events)
        row["checks"] = checks
    except Exception as error:  # noqa: BLE001 - preserve evidence without credential-bearing diagnostics
        row["errorType"] = type(error).__name__
    finally:
        try:
            events = session.event_capture
            provider = provider_summary(_finished_calls(relay, offset))
            application = application_usage(events, provider)
            evidence = turn_evidence(case.effect(), index, events, secrets)
            sql = executed_sql(provider, secrets)
            row.update({**evidence, "provider": scrub(provider, secrets), "application": application,
                        "relayRequests": relay.request_evidence(label, "python"), "syntheticExecutedSql": sql})
            checks = object_value(row.get("checks", {}))
            sse = object_value(evidence["sse"])
            calls = provider["calls"]
            if not isinstance(calls, list):
                raise TypeError("Expected provider call evidence")
            checks.update({"interactionEnded": sse["ended"] is True, "noAbortedOrError":
                           sse["abortedCount"] == sse["errorCount"] == 0, "usageExactlyOnce": sse["usageCount"] == 1,
                           "usageMatchesProvider": application["usageMatchesProvider"] is True,
                           "providerComplete": bool(calls) and all(object_value(call).get("httpStatus") == 200
                           and object_value(call).get("providerDone") is True
                           and object_value(call).get("evidenceError") is None
                           and object_value(call).get("transportError") is None for call in calls)})
            checks["sqlArgumentsObserved"] = len(sql) >= len([tool for tool in tool_results(events)
                                                            if tool.name == "executeSql"])
            if case.clarify:
                checks["classifierOnlyProviderCall"] = len(calls) == 1
            row["checks"] = checks
            review = object_value(row["answerReview"])
            row["status"] = ("failed" if "errorType" in row or not all(checks.values()) or review["status"] == "failed"
                             else "review-required" if review["status"] == "review-required" else "passed")
        except Exception as error:  # noqa: BLE001 - do not erase the original failing stage
            row.update({"status": "failed", "evidenceErrorType": type(error).__name__})
    return row, conversation_id


def run_case(case: Case, repetition: int, relay: RealProviderRelay) -> dict[str, object]:
    turns: list[dict[str, object]] = []
    cleanup: dict[str, dict[str, object]] = {"target": {}, "api": {}}
    row: dict[str, object] = {"case": case.code, "repetition": repetition, "scope": SCOPE,
                              "variant": "python", "database": "postgresql", "status": "failed",
                              "turns": turns, "cleanup": cleanup, "stage": "provision"}
    try:
        with (isolated_database("postgresql", "py", cleanup_evidence=cleanup["target"]) as target,
              api_session("python", relay, cleanup_evidence=cleanup["api"]) as session):
            row["stage"] = "connect"
            db_id = session.connect(target)
            row["stage"] = "upload" if case.attachment else "turns"
            file_id = session.upload_csv() if case.attachment else None
            row["resources"] = {"dbConfigId": db_id, "fileId": file_id, "fixtureDatabase": target.name,
                                "fixtureApiUser": session.username}
            conversation_id: int | None = None
            for index in range(len(case.questions)):
                turn, conversation_id = _turn(case, index, repetition, session, target, relay, db_id,
                                              conversation_id, file_id)
                turns.append(turn)
                if turn["status"] == "failed":
                    break
            row["stage"] = "cleanup"
    except Exception as error:  # noqa: BLE001 - report provisioning and finally cleanup failures explicitly
        row["errorType"] = type(error).__name__
    if ("errorType" in row or len(turns) != len(case.questions) or any(turn["status"] == "failed" for turn in turns)
            or any(item.get("status") != "passed" for item in cleanup.values())):
        row["status"] = "failed"
    else:
        row["status"] = "review-required" if any(turn["status"] == "review-required" for turn in turns) else "passed"
    return row


def main() -> int:
    args = options(__doc__)

    def execute(relay: RealProviderRelay, persist: Callable[[dict[str, object]], None]) -> None:
        for repetition in range(1, REPETITIONS + 1):
            for case in CASES:
                row = run_case(case, repetition, relay)
                persist(row)
                cleanup = object_value(row["cleanup"])
                if any(object_value(item).get("status") != "passed" for item in cleanup.values()):
                    raise RuntimeError("Stop after incomplete fixture cleanup")

    return report_run(args, SCOPE, ("python",), len(CASES) * REPETITIONS, execute)


if __name__ == "__main__":
    raise SystemExit(main())
