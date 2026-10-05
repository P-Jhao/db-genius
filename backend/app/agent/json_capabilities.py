"""Server-only opt-in registry; no provider/model-name inference or I/O."""
import json
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

JsonContract = Literal["classification", "final_report", "task_goal"]


@dataclass(frozen=True)
class ChatJsonCapabilityRule:
    endpoint: str
    model: str
    capability: Literal["chat_json_object"] = "chat_json_object"


def _distinct_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate capability configuration field")
        result[key] = value
    return result


def _rule(value: object) -> ChatJsonCapabilityRule:
    if not isinstance(value, dict) or set(value) != {"endpoint", "model", "capability"}:
        raise ValueError("Invalid capability configuration fields")
    endpoint, model = value["endpoint"], value["model"]
    if not isinstance(endpoint, str) or not isinstance(model, str):
        raise TypeError("Capability endpoint and model must be text")
    if not model or model.strip() != model or len(model) > 128:
        raise ValueError("Invalid capability model")
    if value["capability"] != "chat_json_object":
        raise ValueError("Unsupported chat JSON capability")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid capability endpoint") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            not parsed.path.endswith("/chat/completions") or
            (port is not None and not 0 < port <= 65535) or
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")) != endpoint):
        raise ValueError("Capability endpoint must be an exact credential-free completion URL")
    return ChatJsonCapabilityRule(endpoint, model)


def parse_capability_allowlist(raw: str) -> tuple[ChatJsonCapabilityRule, ...]:
    """Settings default is (); explicit JSON config is strict, empty string is invalid."""
    if len(raw) > 65536:
        raise ValueError("Capability configuration exceeds its bound")
    try:
        values: object = json.loads(raw, object_pairs_hook=_distinct_object)
    except json.JSONDecodeError:
        raise ValueError("Invalid capability configuration JSON") from None
    if not isinstance(values, list) or len(values) > 128:
        raise TypeError("Capability configuration must be a bounded array")
    rules = tuple(_rule(value) for value in values)
    identities = {(rule.endpoint, rule.model) for rule in rules}
    if len(identities) != len(rules):
        raise ValueError("Duplicate endpoint/model capability rule")
    return rules


def chat_json_object_enabled(rules: tuple[ChatJsonCapabilityRule, ...], *,
                             completion_endpoint: str, model_name: str) -> bool:
    """Caller passes completion_url(active.base_url) and active.model_name unchanged."""
    return any(rule.endpoint == completion_endpoint and rule.model == model_name for rule in rules)


def json_contract_options(enabled: bool, contract: JsonContract | None,
                          *, tools_present: bool) -> dict[str, object]:
    """None covers every ordinary call, including all forms of compression/summarizing."""
    if type(enabled) is not bool:
        raise TypeError("JSON capability state must be boolean")
    if contract not in {None, "classification", "final_report", "task_goal"}:
        raise ValueError("Unknown JSON contract call")
    if contract is None or not enabled:
        return {}
    if tools_present:
        raise ValueError("JSON contract calls cannot carry execution tools")
    return {"response_format": {"type": "json_object"}}
