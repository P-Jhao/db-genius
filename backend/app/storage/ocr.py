"""Aliyun RecognizeAdvanced OCR adapter."""

import io
import json
from collections.abc import Callable
from typing import Protocol

from app.core.config import get_settings


class _OcrClient(Protocol):
    def recognize_advanced(self, request: object) -> object: ...


def _client() -> _OcrClient:
    settings = get_settings()
    if not settings.ocr_enabled:
        raise RuntimeError("OCR is disabled")
    ocr_pair = (settings.ocr_access_key_id.strip(), settings.ocr_access_key_secret.strip())
    oss_pair = (settings.oss_access_key_id.strip(), settings.oss_access_key_secret.strip())
    if bool(ocr_pair[0]) != bool(ocr_pair[1]):
        raise RuntimeError("OCR credentials must be configured as a complete pair")
    if ocr_pair[0]:
        access_key_id, access_key_secret = ocr_pair
    else:
        if bool(oss_pair[0]) != bool(oss_pair[1]):
            raise RuntimeError("OSS credentials must be configured as a complete pair for OCR")
        access_key_id, access_key_secret = oss_pair
    if not access_key_id or not access_key_secret or not settings.ocr_endpoint.strip():
        raise RuntimeError("OCR credentials or endpoint are not configured")
    try:
        from alibabacloud_ocr_api20210707.client import Client  # type: ignore[import-untyped]
        from alibabacloud_tea_openapi.models import Config  # type: ignore[import-untyped]
    except ImportError as error:
        raise RuntimeError("Aliyun OCR SDK is unavailable") from error
    return Client(Config(access_key_id=access_key_id, access_key_secret=access_key_secret,
                         endpoint=settings.ocr_endpoint))


def recognize(image_bytes: bytes, *, client_factory: Callable[[], _OcrClient] | None = None) -> str:
    settings = get_settings()
    if not settings.ocr_enabled:
        raise RuntimeError("OCR is disabled")
    if not image_bytes:
        raise ValueError("Image is empty")
    try:
        from alibabacloud_ocr_api20210707.models import (  # type: ignore[import-untyped]
            RecognizeAdvancedRequest,
        )
    except ImportError as error:
        raise RuntimeError("Aliyun OCR SDK is unavailable") from error
    client = client_factory() if client_factory is not None else _client()
    response = client.recognize_advanced(RecognizeAdvancedRequest(body=io.BytesIO(image_bytes)))
    body = getattr(response, "body", None)
    raw = getattr(body, "data", None)
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError("OCR returned no data")
    try:
        result: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("OCR returned invalid JSON") from error
    if not isinstance(result, dict):
        raise TypeError("OCR returned invalid data")
    content = result.get("content")
    if not isinstance(content, str):
        raise TypeError("OCR response has no text content")
    if not content.strip():
        raise RuntimeError("OCR returned empty text content")
    return content
