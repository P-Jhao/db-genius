"""System model window configuration stays separate from saved user models."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import UserModelConfig
from app.services import model_config


@pytest.fixture(autouse=True)
def isolated_environment() -> Iterator[None]:
    with patch.dict("os.environ", {}, clear=True):
        yield


@pytest.mark.parametrize("raw,expected", [("", None), ("16384", 16384), ("1", 1)])
def test_window_environment(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int | None) -> None:
    monkeypatch.setenv("SQLCHAT_DEFAULT_MODEL_CONTEXT_WINDOW", raw)
    assert Settings(_env_file=None).default_model_context_window == expected


def test_window_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SQLCHAT_DEFAULT_MODEL_CONTEXT_WINDOW=32768\n", encoding="utf-8")
    assert Settings(_env_file=env_file).default_model_context_window == 32768


@pytest.mark.parametrize("raw", ["0", "-1", "1.0", "1e4", "abc", " ", " 42", "+42", "true"])
def test_invalid_window_environment(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("SQLCHAT_DEFAULT_MODEL_CONTEXT_WINDOW", raw)
    with pytest.raises(ValidationError, match="default_model_context_window"):
        Settings(_env_file=None)


@pytest.mark.parametrize("raw", [True, False, 1.0, 0, -1])
def test_invalid_window_argument(raw: object) -> None:
    with pytest.raises(ValidationError, match="default_model_context_window"):
        Settings(_env_file=None, default_model_context_window=raw)


@pytest.mark.parametrize("window,name,expected", [
    (None, "deepseek-flash", 1048576), (None, "unknown-model", None),
    (16384, "deepseek-flash", 16384), (16384, "unknown-model", 16384),
])
def test_system_resolution_and_active_response(
    monkeypatch: pytest.MonkeyPatch, window: int | None, name: str, expected: int | None,
) -> None:
    monkeypatch.setenv("SQLCHAT_DEFAULT_MODEL_API_KEY", "synthetic-key")
    settings = Settings(_env_file=None,
                        default_model_name=name, default_model_context_window=window)
    monkeypatch.setattr(model_config, "get_settings", lambda: settings)
    monkeypatch.setattr(model_config, "_active_user_config", lambda _session, _user: None)
    session = Mock(spec=Session)
    resolved = model_config.resolve_active_model(session, 1)
    assert resolved.id is None and resolved.context_window == expected
    assert model_config.active_config_vo(session, 1).model_dump(by_alias=True)["contextWindow"] == expected


@pytest.mark.parametrize("window", [8192, None])
def test_saved_user_window_remains_independent(monkeypatch: pytest.MonkeyPatch, window: int | None) -> None:
    settings = Settings(_env_file=None, default_model_context_window=16384)
    config = UserModelConfig(id=7, user_id=1, provider_code="deepseek", provider_type="openai_compatible",
                            display_name="saved", base_url="https://example.test", model_name="deepseek-flash",
                            api_key_encrypted="synthetic", context_window=window, is_default=True, status=1)
    monkeypatch.setattr(model_config, "get_settings", lambda: settings)
    monkeypatch.setattr(model_config, "_active_user_config", lambda _session, _user: config)
    monkeypatch.setattr(model_config, "decrypt", lambda _key: "synthetic-key")
    resolved = model_config.resolve_active_model(Mock(spec=Session), 1)
    assert resolved.id == 7 and resolved.context_window == window
    assert config.context_window == window
