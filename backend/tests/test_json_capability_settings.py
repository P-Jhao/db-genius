"""Isolated server configuration and explicit acceptance relay-port boundary."""
import json
import socket
from collections.abc import Iterator
from unittest.mock import patch

import pytest
import real_model_regression_support as support
from pydantic import SecretStr, ValidationError
from real_model_relay import RealProviderRelay

from app.agent.json_capabilities import chat_json_object_enabled
from app.core.config import Settings

ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
RULE = {"endpoint": ENDPOINT, "model": "deepseek-flash", "capability": "chat_json_object"}


@pytest.fixture
def isolated_environment() -> Iterator[None]:
    with patch.dict("os.environ", {}, clear=True):
        yield


def test_default_capability_registry_is_empty_without_dotenv(isolated_environment: None) -> None:
    assert Settings(_env_file=None).model_chat_json_capabilities == ()


def test_explicit_capability_environment_matches_final_endpoint_model(
    isolated_environment: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQLCHAT_MODEL_CHAT_JSON_CAPABILITIES", json.dumps([RULE]))
    settings = Settings(_env_file=None)
    assert chat_json_object_enabled(settings.model_chat_json_capabilities, completion_endpoint=ENDPOINT,
                                    model_name="deepseek-flash")
    assert not chat_json_object_enabled(settings.model_chat_json_capabilities, completion_endpoint=ENDPOINT,
                                        model_name="other-model")
    assert not chat_json_object_enabled(settings.model_chat_json_capabilities,
        completion_endpoint="http://host.docker.internal:18080/python/v1/chat/completions", model_name="deepseek-flash")


@pytest.mark.parametrize("raw", ["", "null", "{}", "[", '[{"endpoint":"a","endpoint":"b"}]',
    json.dumps([{**RULE, "providerCode": "custom"}]), json.dumps([{**RULE, "capability": "json_schema"}]),
    json.dumps([RULE, RULE]), json.dumps([{**RULE, "model": True}]),
    json.dumps([{**RULE, "endpoint": ENDPOINT + "?private=value"}])])
def test_invalid_explicit_capability_environment_fails(
    isolated_environment: None, monkeypatch: pytest.MonkeyPatch, raw: str,
) -> None:
    monkeypatch.setenv("SQLCHAT_MODEL_CHAT_JSON_CAPABILITIES", raw)
    with pytest.raises((ValidationError, ValueError, TypeError)):
        Settings(_env_file=None)


def test_explicit_empty_array_preserves_opt_out(isolated_environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLCHAT_MODEL_CHAT_JSON_CAPABILITIES", "[]")
    assert Settings(_env_file=None).model_chat_json_capabilities == ()


@pytest.mark.parametrize("source", ["argument", "environment"])
@pytest.mark.parametrize("invalid_rule", [
    {**RULE, "unknown": "SYNTHETIC_OPERATOR_PRIVATE"},
    {**RULE, "endpoint": "https://user:SYNTHETIC_OPERATOR_PRIVATE@api.deepseek.com/v1/chat/completions"},
], ids=["unknown-field", "credential-url"])
def test_rejected_operator_json_is_hidden_in_actual_settings_error_text(
    isolated_environment: None, monkeypatch: pytest.MonkeyPatch, source: str, invalid_rule: dict[str, str],
) -> None:
    raw = json.dumps([invalid_rule])
    if source == "environment":
        monkeypatch.setenv("SQLCHAT_MODEL_CHAT_JSON_CAPABILITIES", raw)
    with pytest.raises(ValidationError) as caught:
        if source == "argument":
            Settings(_env_file=None, model_chat_json_capabilities=raw)
        else:
            Settings(_env_file=None)
    assert "SYNTHETIC_OPERATOR_PRIVATE" not in str(caught.value)
    assert "input_value=" not in str(caught.value) and "input_type=" not in str(caught.value)
    # .errors() is an internal structure and still carries input; never log/expose it.
    internal = caught.value.errors()
    assert len(internal) == 1 and internal[0]["type"] == "value_error"
    assert internal[0]["loc"] == ("model_chat_json_capabilities",) and internal[0]["input"] == raw


@pytest.mark.parametrize("raw", ["", "0", "-1", "65536", "08080", " 8080", "8080 ", "abc", "1.5"])
def test_invalid_fixed_relay_port_fails_before_provider_access(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("SQLCHAT_REAL_RELAY_PORT", raw)
    with pytest.raises(ValueError, match="SQLCHAT_REAL_RELAY_PORT"):
        support.relay_bind_port()


def test_default_and_explicit_relay_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQLCHAT_REAL_RELAY_PORT", raising=False)
    assert support.relay_bind_port() == 0
    monkeypatch.setenv("SQLCHAT_REAL_RELAY_PORT", "18080")
    assert support.relay_bind_port() == 18080


@pytest.mark.parametrize("port", [-1, 65536, True])
def test_relay_constructor_rejects_invalid_ports(port: int) -> None:
    with pytest.raises(ValueError, match="Relay bind port"):
        RealProviderRelay(SecretStr("synthetic"), bind_port=port)


def test_relay_fixed_port_and_conflict_do_not_fall_back() -> None:
    first = RealProviderRelay(SecretStr("synthetic"))
    port = first.server_port
    try:
        with pytest.raises(OSError):
            RealProviderRelay(SecretStr("synthetic"), bind_port=port)
    finally:
        first.server_close()
    fixed = RealProviderRelay(SecretStr("synthetic"), bind_port=port)
    try:
        assert fixed.server_port == port
    finally:
        fixed.server_close()


def test_explicit_port_is_forwarded_without_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # Constructor binding is real; provider credentials are exclusively synthetic.
    monkeypatch.setattr(support, "provider_key", lambda: SecretStr("synthetic"))
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    monkeypatch.setenv("SQLCHAT_REAL_RELAY_PORT", str(port))
    with support.regression_relay() as relay:
        assert relay.server_port == port
