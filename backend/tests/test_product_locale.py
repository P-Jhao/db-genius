"""Seven source locales keep independent HTTP, SSE, and model language."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_chat_api import parse_events, reply
from test_model_protocol import Provider

from app.agent.prompts import language
from app.core.config import get_settings
from app.core.localization import SUPPORTED_LOCALES, translate
from app.models import DbConfig, User

pytest_plugins = ["test_chat_api"]


@pytest.mark.parametrize("locale", list(SUPPORTED_LOCALES))
def test_trial_errors_and_clarification_keep_request_locale(
    chat_client: tuple[TestClient, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, locale: str,
) -> None:
    client, _, _, _ = chat_client
    monkeypatch.setattr(get_settings(), "trial_enabled", True)
    denied = client.post("/api/chat", headers={"Accept-Language": locale},
                         json={"message": "run", "confirmedIntent": "workflow", "dbConfigIds": [999]})
    assert denied.status_code == 200 and denied.json()["code"] == 403
    assert denied.json()["message"] == translate("error.trial.workflow", locale)
    assert provider.requests == []
    monkeypatch.setattr(get_settings(), "trial_enabled", False)
    provider.replies = [reply(json.dumps({"intent": "sql_query", "confidence": 0.99,
        "reasoning": "reason in " + locale, "needsClarification": False}))]
    response = client.post("/api/chat", headers={"Accept-Language": locale}, json={"message": "query"})
    events = parse_events(response.text)
    clarification = next(event["content"] for event in events if event["type"] == "clarify")
    assert isinstance(clarification, dict)
    options = clarification["options"]
    assert isinstance(options, list) and len(options) == 2
    from app.core.localization import _messages
    resource = _messages(locale)
    assert options == [{"intent": "sql_query", "label": resource["chat.clarify.sqlQueryNeedDb"]},
                       {"intent": "simple_chat", "label": resource["chat.clarify.simpleChat"]}]
    assert clarification["question"] == resource["chat.clarify.question"]
    assert clarification["reasoning"] == translate("error.chat.sqlQueryNoDbConfig", locale)
    classifying = next(event["content"] for event in events if event["type"] == "classifying")
    assert classifying == resource["chat.classifying"]
    messages = provider.requests[0]["messages"]
    assert language(locale) in str(messages)
    assert not any(event["type"] == "error" for event in events)


@pytest.mark.parametrize("intent", ["workflow", "db_compare"])
def test_low_confidence_classified_trial_intent_is_still_rejected(
    chat_client: tuple[TestClient, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, intent: str,
) -> None:
    client, _, _, _ = chat_client
    monkeypatch.setattr(get_settings(), "trial_enabled", True)
    provider.replies = [reply(json.dumps({"intent": intent, "confidence": 0.2,
                                         "reasoning": "uncertain", "needsClarification": True}))]
    events = parse_events(client.post("/api/chat", headers={"Accept-Language": "ja"},
                                     json={"message": "run"}).text)
    assert [event["type"] for event in events][-3:] == ["usage", "error", "done"]
    assert not any(event["type"] in {"clarify", "routing", "summary"} for event in events)
    error = next(event["content"] for event in events if event["type"] == "error")
    key = "error.trial.workflow" if intent == "workflow" else "error.trial.dbCompare"
    assert error == translate(key, "ja") and len(provider.requests) == 1


def test_two_concurrent_http_languages_do_not_leak(
    chat_client: tuple[TestClient, User, User, DbConfig], monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _, _ = chat_client
    monkeypatch.setattr(get_settings(), "trial_enabled", True)

    def request(locale: str) -> str:
        return str(client.post("/api/chat", headers={"Accept-Language": locale},
                               json={"message": "run", "confirmedIntent": "db_compare"}).json()["message"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, ["fr", "ja"]))
    assert results == [translate("error.trial.dbCompare", locale) for locale in ("fr", "ja")]


@pytest.mark.parametrize("locale", list(SUPPORTED_LOCALES))
def test_provider_error_is_localized_but_provider_body_is_never_exposed(
    chat_client: tuple[TestClient, User, User, DbConfig], provider: Provider, locale: str,
) -> None:
    from app.agent.product_locale import stream_error
    client, _, _, _ = chat_client
    provider.replies = [503]
    events = parse_events(client.post("/api/chat", headers={"Accept-Language": locale},
        json={"message": "hi", "confirmedIntent": "simple_chat"}).text)
    error = next(event for event in events if event["type"] == "error")
    assert isinstance(error["taskId"], str)
    assert error["content"] == stream_error(False, locale, error["taskId"])
    assert not any(event["type"] in {"content", "summary"} for event in events)
