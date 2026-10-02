"""Remove configured credentials and URI/header secrets from diagnostics only."""

import json
import re
from urllib.parse import quote, quote_plus, unquote, urlsplit

from app.core.config import Settings
from app.core.errors import BusinessError
from app.core.localization import translate
from app.core.request_locale import current_locale

_URI = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/]*@")
_KEY_NAME = r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie)"
_QUOTED = r"(?:'(?:\\[\s\S]|[^'\\])*'|\"(?:\\[\s\S]|[^\"\\])*\")"
_BARE = r"[^\s,;&}\])]+"
_KEY = re.compile(r"(?i)((?:'" + _KEY_NAME + r"'|\"" + _KEY_NAME + r"\"|" + _KEY_NAME
                  + r")\s*[:=]\s*)(?:" + _QUOTED + r"|(?:bearer|basic)\s+" + _BARE + r"|" + _BARE + r")")


def _credentials(settings: Settings) -> set[str]:
    values = {settings.encrypt_key, settings.default_model_api_key, settings.bootstrap_password,
              settings.oss_access_key_id, settings.oss_access_key_secret,
              settings.ocr_access_key_id, settings.ocr_access_key_secret, settings.trial_builtin_password}
    for url in (settings.database_url, settings.broker_url, settings.checkpoint_database_url):
        if url:
            parsed = urlsplit(url)
            if parsed.password:
                values.add(unquote(parsed.password))
    return {value for value in values if value}


def _variants(credential: str) -> set[str]:
    values = {credential, quote(credential, safe=""), quote_plus(credential)}
    # Python repr and JSON use different quote/escape conventions. Include the
    # inner encoded text so credentials in non-secret-named fields are safe too.
    for value in tuple(values):
        values.update({repr(value)[1:-1], json.dumps(value)[1:-1],
                       json.dumps(value, ensure_ascii=False)[1:-1]})
    return values


def sanitize_diagnostic(message: str, settings: Settings) -> str:
    """Preserve diagnostic wording; never apply this to business schema or rows."""
    if not isinstance(message, str):
        raise TypeError("Diagnostic must be text")
    variants = {variant for credential in _credentials(settings) for variant in _variants(credential)}
    value = message
    for variant in sorted(variants, key=len, reverse=True):
        value = value.replace(variant, "[redacted]")
    value = _URI.sub(r"\1[credentials-redacted]@", value)
    return _KEY.sub(r"\1[redacted]", value)


def safe_exception_diagnostic(error: Exception, settings: Settings) -> str:
    """Translate and redact the full detail before the accepted 1000-character cap."""
    detail = (translate(error.message, current_locale(), *error.message_args)
              if isinstance(error, BusinessError) else str(error))
    return sanitize_diagnostic(f"{type(error).__name__}: {detail}", settings)[:1000]
