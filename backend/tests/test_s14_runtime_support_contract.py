"""Offline boundaries for the formally reproducible S14 runtime helper."""

import hashlib
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
import test_s14_runtime_support as support


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> object:
        pytest.fail("An offline support contract attempted runtime I/O")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(httpx, "Client", refuse)


def request(module: str = "test_s14_runtime_metrics.py") -> pytest.FixtureRequest:
    return cast(pytest.FixtureRequest, SimpleNamespace(module=SimpleNamespace(__file__=module)))


def fixture(request_value: pytest.FixtureRequest) -> object:
    wrapped = cast(Callable[[pytest.FixtureRequest], Iterator[support.Runtime]],
                   support.runtime.__dict__["__wrapped__"])
    return next(wrapped(request_value))


@pytest.mark.usefixtures("no_network")
def test_no_opt_in_skips_before_reading_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQLCHAT_S14_RUNTIME_LIVE", raising=False)
    with pytest.raises(pytest.skip.Exception, match="live opt-in is disabled"):
        fixture(request())


@pytest.mark.usefixtures("no_network")
@pytest.mark.parametrize("module", ["test_s14_runtime_metrics.py", "test_s14_runtime_tracing.py"])
def test_opt_in_without_runtime_names_skips_before_io(
    monkeypatch: pytest.MonkeyPatch, module: str,
) -> None:
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_LIVE", "1")
    for name in (*support._RUNTIME_NAMES, *support._TRACE_NAMES):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(pytest.skip.Exception, match="Missing S14 runtime environment names") as skipped:
        fixture(request(module))
    assert "SQLCHAT_TEST_PG_PASSWORD" in str(skipped.value)
    assert ("SQLCHAT_S14_RUNTIME_CAPTURE_KEY" in str(skipped.value)) is module.endswith("tracing.py")


def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "formal-repository"
    (repo / ".git/acceptance").mkdir(parents=True)
    (repo / ".env.s14").touch()
    monkeypatch.setattr(support, "_REPO", repo)
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_ENV_FILE", str(repo / ".env.s14"))
    return repo


@pytest.mark.usefixtures("no_network")
def test_formal_acceptance_child_is_allowed_without_private_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = repository(tmp_path, monkeypatch)
    report = repo / ".git/acceptance/fresh-runtime"
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_REPORT_DIR", str(report))
    assert support._paths() == (repo / ".env.s14", report)
    assert not report.exists()


@pytest.mark.usefixtures("no_network")
@pytest.mark.parametrize("relative", ["backend/tests", "docs", ".git/acceptance", "../outside"])
def test_reports_outside_a_formal_acceptance_child_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str,
) -> None:
    repo = repository(tmp_path, monkeypatch)
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_REPORT_DIR", str(repo / relative))
    with pytest.raises(ValueError, match="child directory"):
        support._paths()


@pytest.mark.usefixtures("no_network")
def test_other_repository_env_is_rejected_before_runtime_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = repository(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign/.env.s14"
    foreign.parent.mkdir()
    foreign.touch()
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_ENV_FILE", str(foreign))
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_REPORT_DIR", str(repo / ".git/acceptance/fresh"))
    with pytest.raises(ValueError, match="this repository"):
        support._paths()


@pytest.mark.usefixtures("no_network")
def test_prepare_uses_formal_helper_and_explicit_digests_with_only_synthetic_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = repository(tmp_path, monkeypatch)
    report = repo / ".git/acceptance/fresh"
    helper = repo / "backend/tests/deploy_proxy_support.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# synthetic fixture helper\n", encoding="utf-8")
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_API_IMAGE", "sha256:" + "a" * 64)
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_WORKER_IMAGE", "sha256:" + "b" * 64)
    monkeypatch.setenv("SQLCHAT_TEST_DEPLOY_API_CONTAINER", "synthetic-api")
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_WORKER_CONTAINER", "synthetic-worker")
    monkeypatch.setenv("SQLCHAT_TEST_DEPLOY_URL", "http://127.0.0.1:18111")
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_REPORT_DIR", str(report))
    monkeypatch.setenv("SQLCHAT_S14_RUNTIME_DEPLOY_HELPER_SHA", hashlib.sha256(helper.read_bytes()).hexdigest())
    monkeypatch.setattr(support, "dotenv_values", lambda *_args, **_kwargs: {
        "SQLCHAT_BOOTSTRAP_USERNAME": "synthetic-admin", "SQLCHAT_BOOTSTRAP_PASSWORD": "synthetic-password",
    })
    fake = SimpleNamespace(__file__=str(helper))
    monkeypatch.setattr(support, "import_module", lambda _name: fake)
    identities: list[tuple[str, str]] = []
    monkeypatch.setattr(support, "_identity", lambda container, digest: identities.append((container, digest)))
    with pytest.MonkeyPatch.context() as patch:
        deploy, directory, _secrets, worker = support._prepare(patch)
    assert deploy is fake and directory == report and worker == "synthetic-worker"
    assert identities == [("synthetic-api", "sha256:" + "a" * 64), ("synthetic-worker", "sha256:" + "b" * 64)]
    assert report.is_dir()
    monkeypatch.setattr(fake, "__file__", str(repo / ".git/acceptance/private-helper.py"))
    with pytest.MonkeyPatch.context() as patch, pytest.raises(RuntimeError, match="formal tests"):
        support._prepare(patch)
    assert len(identities) == 2
