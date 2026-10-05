"""Three real-model read-only smoke cases, invoked by operator after demo upgrade."""
import argparse
import json
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = [
    "查看当前数据库所有表的所有字段，包含字段类型、是否可空、主键和字段注释，不要遗漏任何表。",
    "统计各分类的已发布文章数量，包含没有已发布文章的分类，按分类编号排序。",
    "查询浏览量最高的三篇已发布文章，展示标题和浏览量，按浏览量降序。",
]


def reasoning_replay(events: list[dict[str, object]], history: list[dict[str, object]]) -> dict[str, object]:
    """Reproduce public SQL-call blocks using step/tool boundaries, without saving their text.

    The public SSE/history contract has no modelCallId. SQL decisions advance steps after
    tool execution; intervening replayable step events split calls. summary_delta is not a
    boundary: a final call can interleave report deltas and reasoning chunks.
    """
    replay: list[tuple[str, object, str]] = []
    for event in events:
        kind = event["type"]
        if kind not in {"reasoning", "step"}:
            continue
        content = event.get("content")
        if not isinstance(content, str):
            raise TypeError("Reasoning and tool SSE content must be text")
        if not content:
            continue
        step = event.get("step")
        if kind == "reasoning" and replay and replay[-1][0] == kind and replay[-1][1] == step:
            previous = replay[-1]
            replay[-1] = (kind, step, previous[2] + content)
        else:
            replay.append((kind, step, content))
    streamed = [item for item in replay if item[0] == "reasoning"]
    saved = [(message["type"], message.get("step"), message["content"])
             for message in history if message.get("type") == "reasoning"]
    history_replay = [(message["type"], message.get("step"), message["content"])
                      for message in history if message.get("type") in {"reasoning", "step"}]
    no_duplicate_fields = all(message.get("reasoningContent") is None for message in history)
    return {"reasoningReplayMatches": streamed == saved and no_duplicate_fields,
            "replayOrderMatches": replay == history_replay,
            "reasoningBlockCount": len(streamed), "historyReasoningBlockCount": len(saved),
            "reasoningBlockCharacters": [len(item[2]) for item in streamed],
            "historyReasoningBlockCharacters": [len(item[2]) for item in saved],
            "reasoningObserved": bool(streamed), "duplicateReasoningFieldsAbsent": no_duplicate_fields}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--browser-only", action="store_true", help="Review existing report without model requests")
    args = parser.parse_args()
    env = dotenv_values(ROOT / ".env")
    base = "http://127.0.0.1:8109"
    token = ""
    def request(path: str, body: object | None = None):
        headers = {"Content-Type": "application/json", "Accept-Language": "zh-CN"}
        if token:
            headers["Authorization"] = token
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        return urlopen(Request(base + "/api" + path, data=data, headers=headers), timeout=300)
    def api(path: str, body: object | None = None):
        with request(path, body) as response:
            value = json.load(response)
        if value.get("code") != 200:
            raise RuntimeError("API smoke precondition failed at " + path)
        return value["data"]
    try:
        login = api("/auth/login", {"username": env.get("SQLCHAT_BOOTSTRAP_USERNAME", "admin"),
                                   "password": env["SQLCHAT_BOOTSTRAP_PASSWORD"]})
        token = login["token"]
        if api("/trial/status")["trialEnabled"] is not True:
            raise RuntimeError("Real demo smoke requires trial mode")
        configs = [item for item in api("/db-config") if item["dbType"] == "*" and item["host"] == "*"]
        if len(configs) != 1 or configs[0]["status"] != 1:
            raise RuntimeError("Expected one healthy trial builtin MySQL configuration")
        active = api("/model-config/active")
        if active["modelName"] != "deepseek-flash":
            raise RuntimeError("Expected existing deepseek-flash model; script never changes model settings")
        report = (json.loads(args.report.read_text(encoding="utf-8")) if args.browser_only
                  else {"model": "deepseek-flash", "cases": []})
        if args.browser_only and (not args.screenshots or not all(
            isinstance(case.get("conversationId"), int) for case in report["cases"]
        )):
            raise ValueError("Browser-only review requires screenshots and report conversation IDs")
        for index, question in enumerate([] if args.browser_only else QUESTIONS):
            events = []
            with request("/chat", {"message": question, "dbConfigIds": [configs[0]["id"]]}) as response:
                if "text/event-stream" not in response.headers.get("Content-Type", ""):
                    raise RuntimeError("Chat did not return SSE")
                for line in response:
                    if line.startswith(b"data:"):
                        events.append(json.loads(line[5:].strip()))
            kinds = [event["type"] for event in events]
            finals = [event["content"] for event in events if event["type"] == "summary"]
            conversations = [event["content"] for event in events if event["type"] == "conversation"]
            conversation_id = conversations[-1] if conversations else None
            final = finals[-1] if finals else ""
            history = [] if conversation_id is None else api(f"/chat/conversations/{conversation_id}/messages")
            summaries = [message["content"] for message in history if message.get("type") == "summary"]
            case = {"question": question, "conversationId": conversation_id,
                    "done": "done" in kinds, "error": "error" in kinds,
                    "reasoningCharacters": sum(len(str(event["content"])) for event in events if event["type"] == "reasoning"),
                    "summaryCharacters": len(final), "summaryCount": len(finals),
                    "historyCount": len(history), "historyMatches": len(summaries) == 1 and summaries[0] == final,
                    "finalContent": final, "stepCount": kinds.count("step")}
            case.update(reasoning_replay(events, history))
            case["passed"] = (case["done"] and not case["error"] and bool(final)
                              and case["historyMatches"] and case["reasoningReplayMatches"]
                              and case["replayOrderMatches"])
            report["cases"].append(case)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.screenshots:
            payload = {"base": base, "login": login, "directory": str(args.screenshots.resolve()),
                       "conversationIds": [case["conversationId"] for case in report["cases"]]}
            result = subprocess.run(["node", "tests/real-blog-demo-review.mjs"], cwd=ROOT / "frontend",
                                    input=json.dumps(payload), text=True, capture_output=True, check=False)
            if result.returncode:
                raise RuntimeError("Browser history review failed at safe stage: " + result.stderr.strip())
        if not all(case["passed"] for case in report["cases"]):
            raise AssertionError("Some real-model cases failed; inspect safe report")
        print("Existing conversation browser review passed" if args.browser_only else
              "Three real-model SSE/history smoke cases passed; safe report saved")
    finally:
        if token:
            api("/auth/logout", {})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - sanitize the top-level credential-bearing HTTP boundary
        # Do not emit request/response body, credentials, token, or provider payload.
        print("Real demo verification failed: " + type(error).__name__)
        if isinstance(error, RuntimeError) and str(error).startswith("Browser history review failed at safe stage:"):
            print(str(error))
        raise SystemExit(1) from None
