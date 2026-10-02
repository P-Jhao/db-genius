from celery import Task  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.observability_logging import configure_logging
from app.core.observability_metrics import verification_finished
from app.core.observability_tracing import configure_tracing, extract_headers, span
from app.core.request_locale import current_locale, locale_scope
from app.services.db_config_worker import verify_and_generate
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="sqlchat.db_config.verify", time_limit=120)  # type: ignore[untyped-decorator]
def verify_config(task: Task, config_id: int, version: int) -> None:
    headers = task.request.headers
    locale = headers.get("locale") if isinstance(headers, dict) else None
    if locale is not None and not isinstance(locale, str):
        raise TypeError("Verification task locale must be a string")
    configure_logging(get_settings())
    configure_tracing(get_settings(), service_name="sqlchat-worker")
    task_id = task.request.id
    with locale_scope(locale), span("celery.db_config.verify",
                                   task_id=task_id if isinstance(task_id, str) else None,
                                   attributes={"chat.locale": current_locale()},
                                   parent=extract_headers(headers if isinstance(headers, dict) else {})):
        try:
            verify_and_generate(config_id, version)
        except BaseException:
            verification_finished("error")
            raise
