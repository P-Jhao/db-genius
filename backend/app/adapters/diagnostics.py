"""Remove configured secrets and URI credentials from public driver diagnostics."""

import re
from urllib.parse import quote, quote_plus

from app.adapters.types import DbConnectionConfig

_URI_CREDENTIALS = re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s]*@", re.IGNORECASE)


def sanitize_diagnostic(message: str, config: DbConnectionConfig) -> str:
    if not isinstance(message, str):
        raise TypeError("Database diagnostic must be text")
    if not isinstance(config.password, str):
        raise TypeError("Database password must be text")
    if config.password:
        secrets = {config.password, quote(config.password, safe=""), quote_plus(config.password)}
        for secret in sorted(secrets, key=len, reverse=True):
            message = message.replace(secret, "[REDACTED]")
    return _URI_CREDENTIALS.sub(r"\1[REDACTED]@", message)
