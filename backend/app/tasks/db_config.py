from celery import Task  # type: ignore[import-untyped]

from app.core.request_locale import locale_scope
from app.services.db_config_worker import verify_and_generate
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="sqlchat.db_config.verify", time_limit=120)  # type: ignore[untyped-decorator]
def verify_config(task: Task, config_id: int, version: int) -> None:
    headers = task.request.headers
    locale = headers.get("locale") if isinstance(headers, dict) else None
    if locale is not None and not isinstance(locale, str):
        raise TypeError("Verification task locale must be a string")
    with locale_scope(locale):
        verify_and_generate(config_id, version)
