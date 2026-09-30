import logging
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.schemas.model_config import ContextWindowLookupVO

logger = logging.getLogger(__name__)

EXACT_WINDOWS = {
    "deepseek-chat": 65536, "deepseek-reasoner": 65536,
    "deepseek-v3": 65536, "deepseek-v4-pro": 65536,
    "deepseek-flash": 1048576,
    "gpt-4-turbo": 131072, "gpt-3.5-turbo": 16385,
    "qwen-max": 32768, "qwen-plus": 131072, "qwen-turbo": 131072,
    "glm-4": 131072, "glm-4-plus": 131072,
    "moonshot-v1-32k": 32768, "moonshot-v1-128k": 131072,
}
PREFIX_WINDOWS = (
    ("gpt-4.1", 1047576), ("gpt-4o", 131072), ("o3", 200000),
    ("o4-mini", 200000), ("deepseek", 65536), ("kimi", 131072),
    ("glm", 131072), ("qwen", 131072),
)


def known_context_window(model_name: str) -> int | None:
    name = model_name.strip().lower()
    exact = EXACT_WINDOWS.get(name)
    if exact is not None:
        return exact
    for prefix, window in PREFIX_WINDOWS:
        if name.startswith(prefix):
            return window
    return None


def models_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("baseUrl must be an absolute HTTP URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("baseUrl must not contain credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path.removesuffix("/chat/completions") + "/models"
    elif path.endswith("/v1"):
        path += "/models"
    else:
        path += "/v1/models"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def lookup_context_window(base_url: str, api_key: str, model_name: str) -> ContextWindowLookupVO:
    window = known_context_window(model_name)
    if window is not None:
        return ContextWindowLookupVO(model_name=model_name, context_window=window, source="registry")
    # The OpenAI-compatible models endpoint does not define a context-window field.
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(models_url(base_url), headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
        logger.debug("Model list probe succeeded for an unknown model")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Model list probe failed: %s", type(exc).__name__)
    return ContextWindowLookupVO(model_name=model_name, context_window=None, source="not_found")
