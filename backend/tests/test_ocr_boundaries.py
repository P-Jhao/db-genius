"""OCR configuration pairs and empty recognition cannot produce success."""

import json
from types import SimpleNamespace

import pytest
from alibabacloud_ocr_api20210707 import client as sdk_client

from app.core.config import Settings
from app.storage import ocr


@pytest.mark.parametrize("content", ["", " \n\t", None, 123])
def test_ocr_rejects_empty_or_nontext_content(monkeypatch: pytest.MonkeyPatch, content: object) -> None:
    class Client:
        def recognize_advanced(self, _request: object) -> object:
            return SimpleNamespace(body=SimpleNamespace(data=json.dumps({"content": content})))

    monkeypatch.setattr(ocr, "get_settings", lambda: Settings(ocr_enabled=True))
    with pytest.raises((RuntimeError, TypeError), match="text content"):
        ocr.recognize(b"image", client_factory=Client)


@pytest.mark.parametrize("ocr_pair,oss_pair,expected", [
    (("ocr-id", "ocr-secret"), ("oss-id", "oss-secret"), ("ocr-id", "ocr-secret")),
    (("", ""), ("oss-id", "oss-secret"), ("oss-id", "oss-secret")),
])
def test_ocr_uses_a_complete_selected_pair(
    monkeypatch: pytest.MonkeyPatch, ocr_pair: tuple[str, str], oss_pair: tuple[str, str],
    expected: tuple[str, str],
) -> None:
    captured: list[tuple[str, str]] = []

    class Client:
        def __init__(self, config: object) -> None:
            captured.append((config.access_key_id, config.access_key_secret))  # type: ignore[attr-defined]

        def recognize_advanced(self, _request: object) -> object:
            return SimpleNamespace(body=SimpleNamespace(data='{"content":"recognized"}'))

    monkeypatch.setattr(sdk_client, "Client", Client)
    monkeypatch.setattr(ocr, "get_settings", lambda: Settings(
        ocr_enabled=True, ocr_access_key_id=ocr_pair[0], ocr_access_key_secret=ocr_pair[1],
        oss_access_key_id=oss_pair[0], oss_access_key_secret=oss_pair[1]))
    assert ocr.recognize(b"image") == "recognized"
    assert captured == [expected]


@pytest.mark.parametrize("ocr_pair,oss_pair", [
    (("id", ""), ("oss-id", "oss-secret")),
    (("", "secret"), ("oss-id", "oss-secret")),
    (("", ""), ("oss-id", "")),
    (("", ""), ("", "oss-secret")),
    ((" ", "secret"), ("oss-id", "oss-secret")),
])
def test_ocr_does_not_mix_partial_credentials(
    monkeypatch: pytest.MonkeyPatch, ocr_pair: tuple[str, str], oss_pair: tuple[str, str],
) -> None:
    monkeypatch.setattr(ocr, "get_settings", lambda: Settings(
        ocr_enabled=True, ocr_access_key_id=ocr_pair[0], ocr_access_key_secret=ocr_pair[1],
        oss_access_key_id=oss_pair[0], oss_access_key_secret=oss_pair[1]))
    with pytest.raises(RuntimeError, match="complete pair"):
        ocr.recognize(b"image")
