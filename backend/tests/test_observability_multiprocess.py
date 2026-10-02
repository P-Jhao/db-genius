"""Independent writers emulate colliding PID namespaces and scrape one HTTP API."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.core.config import get_settings
from app.main import app

_SCRIPT = """
import json, sys, time
from prometheus_client import values
values.ValueClass = values.MultiProcessValue(process_identifier=lambda: int(sys.argv[3]))
from app.core.observability_metrics import first_chunk, queue_call, verification_finished
service, count = sys.argv[1], int(sys.argv[2])
first_chunk(0.25)
print('ready', flush=True)
sys.stdin.readline()
for i in range(count):
    if service == 'api': queue_call('done')
    else: verification_finished(('done', 'partial', 'stale', 'error')[i % 4])
    if i % 20 == 0: time.sleep(0.002)
print(json.dumps({'completed': count}), flush=True)
"""


def value(client: TestClient, name: str, **labels: str) -> float:
    response = client.get("/api/metrics")
    assert response.status_code == 200
    samples = [s for m in text_string_to_metric_families(response.text) for s in m.samples
               if s.name == name and s.labels == labels]
    assert len(samples) <= 1, "Multiprocess and local registries must not duplicate a series"
    assert all("pid" not in s.labels for m in text_string_to_metric_families(response.text) for s in m.samples)
    return samples[0].value if samples else 0.0


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Path]]:
    for name in ("api", "worker"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(get_settings(), "metrics_multiprocess_root", str(tmp_path))
    # The collector is independent of writer state in this pytest process. The
    # writers set environment before import; Linux process locks have their own gate.
    yield TestClient(app), tmp_path


def launch(root: Path, service: str, count: int, pid: int = 1) -> subprocess.Popen[str]:
    environment = dict(os.environ)
    environment["PROMETHEUS_MULTIPROC_DIR"] = str(root / service)
    environment["SQLCHAT_METRICS_MULTIPROCESS_ROOT"] = str(root)
    child = subprocess.Popen([sys.executable, "-B", "-c", _SCRIPT, service, str(count), str(pid)],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert child.stdout is not None and child.stdout.readline().strip() == "ready"
    return child


def finish(child: subprocess.Popen[str], count: int) -> None:
    output, error = child.communicate(timeout=20)
    assert child.returncode == 0, error
    assert json.loads(output)["completed"] == count


def test_same_pid_two_directories_concurrent_writers_and_restart(
    client: tuple[TestClient, Path],
) -> None:
    http, root = client
    assert value(http, "sqlchat_queue_publications_total", outcome="done") == 0
    api, worker = launch(root, "api", 160), launch(root, "worker", 160)
    try:
        for child in (api, worker):
            assert child.stdin is not None
            child.stdin.write("go\n")
            child.stdin.flush()
        for _ in range(6):
            assert 0 <= value(http, "sqlchat_queue_publications_total", outcome="done") <= 160
        finish(api, 160)
        finish(worker, 160)
    finally:
        for child in (api, worker):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
    assert {p.name for p in (root / "api").glob("*.db")} == {"counter_1.db", "histogram_1.db"}
    assert {p.name for p in (root / "worker").glob("*.db")} == {"counter_1.db", "histogram_1.db"}
    assert value(http, "sqlchat_queue_publications_total", outcome="done") == 160
    for outcome in ("done", "partial", "stale", "error"):
        assert value(http, "sqlchat_verifications_total", outcome=outcome) == 40
    assert value(http, "sqlchat_chat_first_chunk_seconds_count") == 2
    assert http.get("/api/metrics").content == http.get("/metrics").content
    for _ in range(3):
        assert value(http, "sqlchat_verifications_total", outcome="done") == 40
    # A process/service restart reopens the same namespace PID file. Existing
    # history belongs to this stack epoch and must not be counted again.
    restarted = launch(root, "worker", 4)
    try:
        assert restarted.stdin is not None
        restarted.stdin.write("go\n")
        restarted.stdin.flush()
        finish(restarted, 4)
    finally:
        if restarted.poll() is None:
            restarted.terminate()
            restarted.wait(timeout=5)
    for outcome in ("done", "partial", "stale", "error"):
        assert value(http, "sqlchat_verifications_total", outcome=outcome) == 41
    assert value(http, "sqlchat_queue_publications_total", outcome="done") == 160
    assert value(http, "sqlchat_chat_first_chunk_seconds_count") == 3

    # API PID1 restart preserves worker history and resumes only its own file.
    restarted_api = launch(root, "api", 7)
    try:
        assert restarted_api.stdin is not None
        restarted_api.stdin.write("go\n")
        restarted_api.stdin.flush()
        finish(restarted_api, 7)
    finally:
        if restarted_api.poll() is None:
            restarted_api.terminate()
            restarted_api.wait(timeout=5)
    assert value(http, "sqlchat_queue_publications_total", outcome="done") == 167
    for outcome in ("done", "partial", "stale", "error"):
        assert value(http, "sqlchat_verifications_total", outcome=outcome) == 41
    # Different child PIDs inside the worker namespace merge without pid labels.
    children = [launch(root, "worker", 8, pid) for pid in (2, 3)]
    try:
        for child in children:
            assert child.stdin is not None
            child.stdin.write("go\n")
            child.stdin.flush()
        for child in children:
            finish(child, 8)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
    for outcome in ("done", "partial", "stale", "error"):
        assert value(http, "sqlchat_verifications_total", outcome=outcome) == 45
    assert value(http, "sqlchat_queue_publications_total", outcome="done") == 167
    assert value(http, "sqlchat_chat_first_chunk_seconds_count") == 6
    assert value(http, "sqlchat_chat_first_chunk_seconds_sum") == 1.5
    assert value(http, "sqlchat_chat_first_chunk_seconds_bucket", le="0.1") == 0
    assert value(http, "sqlchat_chat_first_chunk_seconds_bucket", le="0.25") == 6
    assert value(http, "sqlchat_chat_first_chunk_seconds_bucket", le="+Inf") == 6
    assert http.get("/api/metrics").content == http.get("/metrics").content
