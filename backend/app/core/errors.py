from typing import TypeVar

T = TypeVar("T")


class BusinessError(Exception):
    def __init__(self, code: int, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def success(data: T = None) -> dict[str, object]:
    return {"code": 200, "message": "success", "data": data}


def deny_trial() -> None:
    from app.core.config import get_settings
    if get_settings().trial_enabled:
        raise BusinessError(403, "error.trial.denied", 403)
