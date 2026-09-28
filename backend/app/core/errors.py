from app.core.config import get_settings


class BusinessError(Exception):
    def __init__(self, code: int, message: str, status_code: int = 200, *message_args: object) -> None:
        if not isinstance(code, int) or isinstance(code, bool):
            raise TypeError("BusinessError code must be an integer")
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.message_args = message_args


def success[T](data: T | None = None) -> dict[str, object]:
    return {"code": 200, "message": "success", "data": data}


def deny_trial(message: str = "error.trial.denied") -> None:
    if get_settings().trial_enabled:
        raise BusinessError(403, message)
