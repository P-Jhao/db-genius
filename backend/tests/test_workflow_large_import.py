"""Real 200-row imports survive model cropping, artifact pages and the SQL row cap."""

import json
import threading
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Handler, Provider
from test_workflow_integration import (
    DB_ID,
    actual_rows,
    answer_reply,
    install_target,
    run,
    target_table,
    tool_reply,
    upload_csv,
)
from test_workflow_integration import (
    upload_store as upload_store_fixture,
)

upload_store = upload_store_fixture


class PagingProvider(Provider):
    def __init__(self) -> None:
        super().__init__([])
        self.RequestHandlerClass = PagingHandler
        self.plan: list[list[bytes]] = []
        self.page_parts: list[str] = []
        self.artifact_id = ""
        self.source_preview: dict[str, object] = {}


class PagingHandler(Handler):
    def do_POST(self) -> None:
        service = self.server
        assert isinstance(service, PagingProvider)
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        service.requests.append(request)
        messages = request["messages"]
        last = messages[-1]
        call_id = last.get("tool_call_id", "")
        if call_id == "source":
            preview = json.loads(last["content"])
            assert preview["marker"] == "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]"
            service.source_preview = preview
            service.artifact_id = preview["artifactId"]
            reply = tool_reply("readToolOutput", {"artifact_id": service.artifact_id,
                               "offset": 0, "length": 16000}, "page_0")
        elif call_id.startswith("page_"):
            page = json.loads(last["content"])
            service.page_parts.append(page["content"])
            reply = (tool_reply("readToolOutput", {"artifact_id": service.artifact_id,
                     "offset": page["nextOffset"], "length": 16000}, f"page_{page['nextOffset']}")
                     if page["hasMore"] else service.plan.pop(0))
        else:
            reply = service.plan.pop(0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for part in reply:
            self.wfile.write(part)
            self.wfile.flush()


@pytest.fixture
def paging_provider() -> Iterator[PagingProvider]:
    provider = PagingProvider()
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    yield provider
    provider.shutdown()
    provider.server_close()
    thread.join(timeout=2)


def source_row(index: int) -> tuple[int, str, str]:
    return index, f"Customer_{index:03d}_abcdefghijkl", f"City_{index:03d}"


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
@pytest.mark.parametrize("total_rows", [200, 207])
async def test_real_import_pages_batches_and_multiple_selects(
    db_type: str, total_rows: int, paging_provider: PagingProvider,
    upload_store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    with target_table(db_type) as (config, table):
        install_target(monkeypatch, config)
        content = ("id,name,city\n" + "".join(
            f"{i},{name},{city}\n" for i, name, city in map(source_row, range(1, total_rows + 1)))).encode()
        uploaded = upload_csv(upload_store, content)
        service = paging_provider
        service.plan = [tool_reply("readFile", {"file_id": uploaded.id}, "source")]
        for start in range(1, 201, 50):
            values = ",".join(f"({i},'{name}','{city}')" for i, name, city in
                              map(source_row, range(start, start + 50)))
            service.plan.append(tool_reply("executeSql", {"db_id": DB_ID,
                "statement": f"INSERT INTO {table} (id,name,city) VALUES {values}"}, f"insert_{start}"))
        service.plan.extend([
            tool_reply("executeSql", {"db_id": DB_ID,
                "statement": f"SELECT id,name,city FROM {table} ORDER BY id"}, "verify_first"),
            tool_reply("executeSql", {"db_id": DB_ID,
                "statement": f"SELECT id,name,city FROM {table} ORDER BY id LIMIT 100 OFFSET 100"}, "verify_rest"),
            tool_reply("doTerminate", {"reason": "verified"}, "done"),
            answer_reply("All source rows were imported and verified."),
        ])
        result, events = await run(service, uploaded.id)
        assert actual_rows(config, table) == [source_row(i) for i in range(1, 201)]
        recovered = json.loads("".join(service.page_parts))
        assert len(service.page_parts) > 1
        assert recovered["totalRows"] == total_rows and len(recovered["data"]) == 200
        assert recovered["truncated"] is (total_rows > 200)
        assert service.source_preview["sourceTruncated"] is (total_rows > 200)
        assert service.source_preview["returnedItems"] <= 50
        raw_steps = [item for kind, item in events if kind == "step" and isinstance(item, str)]
        raw_source = json.loads(next(item.removeprefix("readFile: ") for item in raw_steps
                                    if item.startswith("readFile: ")))
        assert raw_source == recovered  # History/SSE keep full original service output.
        query_results = [json.loads(item.removeprefix("executeSql: ")) for item in raw_steps
                         if item.startswith("executeSql: ") and '"rowCount"' in item]
        assert [item["rowCount"] for item in query_results] == [100, 100]
        assert query_results[0]["truncated"] is True
        if total_rows == 200:
            assert result == "All source rows were imported and verified."
        else:
            assert "Only 200 of 207 source rows were inserted" in result
            assert "partial import" in result
            assert "All source rows were imported" not in result
            assert not any(row["id"] == "201" for row in recovered["data"])
        assert service.plan == []
