"""Explicit live gate; reuse deployment ownership and accepted target fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import wraps
from importlib import import_module
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
from typing import Protocol, cast
from urllib.parse import quote, quote_plus, unquote, urlsplit

import httpx
import pytest
from dotenv import dotenv_values
from prometheus_client.parser import text_string_to_metric_families
from pydantic import SecretStr
from real_model_database import TargetSnapshot

_REPO = Path(__file__).resolve().parents[2]
_RUNTIME_NAMES = (
    "SQLCHAT_S14_RUNTIME_API_IMAGE", "SQLCHAT_S14_RUNTIME_WORKER_IMAGE", "SQLCHAT_TEST_DEPLOY_API_CONTAINER",
    "SQLCHAT_S14_RUNTIME_WORKER_CONTAINER", "SQLCHAT_TEST_DEPLOY_URL", "SQLCHAT_S14_RUNTIME_ENV_FILE",
    "SQLCHAT_S14_RUNTIME_DEPLOY_HELPER_SHA", "SQLCHAT_S14_RUNTIME_REPORT_DIR",
    "SQLCHAT_TEST_PG_HOST", "SQLCHAT_TEST_PG_PORT", "SQLCHAT_TEST_PG_DB", "SQLCHAT_TEST_PG_USER", "SQLCHAT_TEST_PG_PASSWORD",
)
_TRACE_NAMES = ("SQLCHAT_S14_RUNTIME_OTLP_EXPORT_URL", "SQLCHAT_S14_RUNTIME_OTLP_BIND", "SQLCHAT_S14_RUNTIME_CAPTURE_KEY")


class Proxy(Protocol):
    client: httpx.Client
    container: str
    username: str
    token: str


class Deploy(Protocol):
    __file__: str
    def open_proxy_session(self) -> tuple[Proxy, Thread]: ...
    def close_proxy_session(self, target: Proxy, thread: Thread) -> None: ...
    def runtime_script(self, container: str, script: str, *arguments: str) -> str: ...
    def api(self, client: httpx.Client, method: str, path: str, *, json: object = None) -> object: ...


def required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise ValueError("Missing explicit runtime acceptance configuration")
    return value


def obj(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Expected runtime JSON object")
    return cast(dict[str, object], value)


def safe_live[**P](case: Callable[P, None]) -> Callable[P, None]:
    @wraps(case)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            case(*args, **kwargs)
        except Exception:  # noqa: BLE001 - fail without credential-bearing traceback context
            # Do not retain provider/driver/HTTP exceptions or credential-bearing
            # assertion locals in pytest's traceback/repr. Failure still fails.
            raise RuntimeError(f"{case.__name__} failed; diagnostic content suppressed") from None
    return run


def _identity(container: str, expected: str) -> None:
    result = subprocess.run(["docker", "inspect", "--format", ("{{.Image}}|"
                             '{{index .Config.Labels "com.docker.compose.project"}}|{{.State.Running}}'), container],
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode or result.stdout.strip() != expected + "|sqlchat-s14-test|true":
        raise RuntimeError("Final runtime image/project identity did not match")


@dataclass(frozen=True)
class State:
    status: int
    document: bool
    warning: bool
    digest: str = field(repr=False)


@dataclass(repr=False)
class Runtime:
    deploy: Deploy = field(repr=False)
    session: Proxy = field(repr=False)
    report_dir: Path = field(repr=False)
    secrets: tuple[SecretStr, ...] = field(repr=False)
    worker: str = field(repr=False)
    processes: int = 0

    def __repr__(self) -> str:
        return "<S14Runtime protected>"

    def script(self, script: str, *args: str) -> str:
        return self.deploy.runtime_script(self.session.container, script, *args)

    def create(self, target: TargetSnapshot, locale: str = "en", *, bad: bool = False,
               headers: Mapping[str, str] | None = None) -> int:
        payload = target.request()
        if bad:
            payload["password"] = SecretStr(os.urandom(24).hex()).get_secret_value()
        with httpx.Client(base_url=self.session.client.base_url, headers=self.session.client.headers,
                          timeout=30) as client:
            client.headers["Accept-Language"] = locale
            if headers is not None:
                client.headers.update(headers)
            created = obj(self.deploy.api(client, "POST", "db-config", json=payload))
        identifier = created.get("id")
        if type(identifier) is not int or created.get("status") != 0:
            raise RuntimeError("Actual verification did not start pending")
        return identifier

    def state(self, identifier: int) -> State:
        data = obj(self.deploy.api(self.session.client, "GET", f"db-config/{identifier}"))
        status, document = data.get("status"), data.get("docContent")
        if type(status) is not int or status not in {0, 1, 2}:
            raise TypeError("Unexpected actual configuration status")
        if document is not None and not isinstance(document, str):
            raise TypeError("Actual document must be string or null")
        generated = data.get("docGeneratedAt")
        if generated is not None and not isinstance(generated, str):
            raise TypeError("Actual document timestamp must be string or null")
        text = "" if document is None else document
        return State(status, bool(text), "Error reading metadata" in text,
                     hashlib.sha256(json.dumps([text, generated]).encode()).hexdigest())

    def completed(self, identifier: int) -> State:
        deadline = monotonic() + 60
        while True:
            state = self.state(identifier)
            if state.status != 0:
                return state
            if monotonic() >= deadline:
                raise TimeoutError("Real worker did not finish")
            sleep(0.2)

    def metric(self, name: str, *, direct: bool = False, **labels: str) -> float:
        if direct:
            packet = obj(json.loads(self.script(
                "import json; from urllib.request import build_opener,ProxyHandler; "
                "r=build_opener(ProxyHandler({})).open('http://127.0.0.1:8109/metrics',timeout=5); "
                "print(json.dumps({'type':r.headers.get('Content-Type',''),'body':r.read().decode()})); r.close()")))
            content_type, text = packet.get("type"), packet.get("body")
        else:
            response = self.session.client.get("metrics")  # /api/metrics, never external SPA /metrics
            if response.status_code != 200:
                raise RuntimeError("Canonical metric scrape failed")
            content_type, text = response.headers.get("Content-Type", ""), response.text
        if not isinstance(content_type, str) or not content_type.startswith("text/plain") or not isinstance(text, str):
            raise TypeError("Metrics must be Prometheus text, not HTML/R-wrapped JSON")
        for family in text_string_to_metric_families(text):
            for sample in family.samples:
                if sample.name == name and sample.labels == labels:
                    return float(sample.value)
        return 0.0

    def counter_after(self, outcome: str, before: float) -> float:
        deadline = monotonic() + 60
        while True:
            after = self.metric("sqlchat_verifications_total", outcome=outcome)
            if after > before:
                return after
            if monotonic() >= deadline:
                raise TimeoutError("Worker counter was not observable from the API")
            sleep(0.2)

    def stale(self, identifier: int, headers: Mapping[str, str] | None = None) -> None:
        packet = obj(json.loads(self.script(
            "import json,sys; from sqlalchemy import select; from app.core.database import SessionLocal; "
            "from app.models import User,DbConfig; from app.tasks.db_config import verify_config; "
            "s=SessionLocal(); c=s.scalar(select(DbConfig).join(User,User.id==DbConfig.user_id).where("
            "User.username==sys.argv[1],DbConfig.id==int(sys.argv[2]))); "
            "assert c is not None and c.status==1 and c.verification_version>0; "
            "verify_config.apply_async(args=(c.id,c.verification_version-1),headers=json.loads(sys.argv[3])); "
            "s.close(); print(json.dumps({'published':True}))", self.session.username,
            str(identifier), json.dumps({} if headers is None else dict(headers)))))
        if packet.get("published") is not True:
            raise RuntimeError("Exact owned stale callback was not published")

    def absent(self, payload: bytes, *extra: SecretStr) -> bool:
        values = (*self.secrets, SecretStr(self.session.token), *extra)
        return all(variant.encode() not in payload for secret in values if secret.get_secret_value()
                   for variant in {secret.get_secret_value(), quote(secret.get_secret_value(), safe=""),
                                   quote_plus(secret.get_secret_value())})

    def report(self, case: str, values: dict[str, bool | int | float]) -> None:
        if re.fullmatch(r"[a-z_]+", case) is None:
            raise ValueError("Only fixed report case names are allowed")
        with (self.report_dir / f"{case}.json").open("x", encoding="utf-8") as handle:
            json.dump(values, handle, sort_keys=True, indent=2)
            handle.write("\n")


def _paths() -> tuple[Path, Path]:
    env = Path(required("SQLCHAT_S14_RUNTIME_ENV_FILE")).resolve(strict=True)
    if env != _REPO / ".env.s14" or not (_REPO / ".git").is_dir():
        raise ValueError("Only this repository's root-owned runtime .env.s14 is accepted")
    report = Path(required("SQLCHAT_S14_RUNTIME_REPORT_DIR")).resolve()
    allowed = (_REPO / ".git/acceptance").resolve()
    if report == allowed or not report.is_relative_to(allowed):
        raise ValueError("Reports require a child directory of this repository's acceptance directory")
    return env, report


def _prepare(patch: pytest.MonkeyPatch) -> tuple[Deploy, Path, tuple[SecretStr, ...], str]:
    api_image = required("SQLCHAT_S14_RUNTIME_API_IMAGE")
    worker_image = required("SQLCHAT_S14_RUNTIME_WORKER_IMAGE")
    for image in (api_image, worker_image):
        if re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
            raise ValueError("Explicit immutable final image digests are required")
    worker = required("SQLCHAT_S14_RUNTIME_WORKER_CONTAINER")
    url = urlsplit(required("SQLCHAT_TEST_DEPLOY_URL"))
    if url.hostname not in {"127.0.0.1", "localhost"} or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
        raise ValueError("Runtime test URL must identify the isolated loopback gateway")
    env, report = _paths()
    values = dotenv_values(env, interpolate=False)
    for key, source in (("SQLCHAT_TEST_DEPLOY_USERNAME", "SQLCHAT_BOOTSTRAP_USERNAME"),
                        ("SQLCHAT_TEST_DEPLOY_PASSWORD", "SQLCHAT_BOOTSTRAP_PASSWORD")):
        value = values.get(source)
        if not isinstance(value, str) or not value:
            raise ValueError("Root runtime administrator must be configured")
        patch.setenv(key, value)
    deploy = cast(Deploy, import_module("deploy_proxy_support"))
    if Path(deploy.__file__).resolve() != _REPO / "backend/tests/deploy_proxy_support.py":
        raise RuntimeError("Deployment helper must resolve to this repository's formal tests")
    expected = required("SQLCHAT_S14_RUNTIME_DEPLOY_HELPER_SHA")
    if hashlib.sha256(Path(deploy.__file__).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Root/Luna final helper SHA did not match")
    _identity(required("SQLCHAT_TEST_DEPLOY_API_CONTAINER"), api_image)
    _identity(worker, worker_image)
    report.mkdir(parents=True, exist_ok=True)
    secrets = tuple(SecretStr(value) for key, value in values.items() if value and
                    re.search(r"PASSWORD|SECRET|ENCRYPT_KEY|API_KEY", key))
    uri_passwords = tuple(SecretStr(unquote(password)) for value in values.values() if value and "://" in value
                          if (password := urlsplit(value).password) is not None)
    return deploy, report, (*secrets, *uri_passwords), worker


@pytest.fixture
def runtime(request: pytest.FixtureRequest) -> Iterator[Runtime]:
    if os.environ.get("SQLCHAT_S14_RUNTIME_LIVE") != "1":
        pytest.skip("Explicit final-image S14 live opt-in is disabled")
    trace_names = _TRACE_NAMES if Path(request.module.__file__).name == "test_s14_runtime_tracing.py" else ()
    missing = [name for name in (*_RUNTIME_NAMES, *trace_names) if not os.environ.get(name)]
    if missing:
        pytest.skip("Missing S14 runtime environment names: " + ", ".join(missing))
    deploy: Deploy | None = None
    target: Proxy | None = None
    thread: Thread | None = None
    live: Runtime | None = None
    with pytest.MonkeyPatch.context() as patch:
        try:
            try:
                deploy, report, secrets, worker = _prepare(patch)
                target, thread = deploy.open_proxy_session()
                live = Runtime(deploy, target, report, secrets, worker)
                preflight = obj(json.loads(live.script(
                    "import json; from app.tasks.celery_app import celery_app as c; "
                    "s=c.control.inspect(timeout=3).stats(); "
                    "print(json.dumps({'prefork':bool(s) and all('prefork' in v['pool']['implementation'] "
                    "for v in s.values()),'not_eager':not c.conf.task_always_eager, "
                    "'processes':sum(len(v['pool']['processes']) for v in s.values())}))")))
                if preflight.get("prefork") is not True or preflight.get("not_eager") is not True:
                    raise RuntimeError("Actual non-eager prefork worker is required")
                count = preflight.get("processes")
                if type(count) is not int or not 1 <= count <= 16:
                    raise RuntimeError("A bounded actual prefork pool is required")
                live.processes = count
            except Exception:  # noqa: BLE001 - fail without credential-bearing traceback context
                raise RuntimeError("S14 runtime setup failed; diagnostic content suppressed") from None
            yield live
        finally:
            if deploy is not None and target is not None and thread is not None:
                try:
                    deploy.close_proxy_session(target, thread)
                    if live is not None:
                        live.report("owner_cleanup_" + request.node.name, {"owner_cleanup": True})
                except Exception:  # noqa: BLE001 - fail without credential-bearing traceback context
                    raise RuntimeError("Exact runtime owner cleanup failed; diagnostic content suppressed") from None
