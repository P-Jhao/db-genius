from celery import Celery  # type: ignore[import-untyped]

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("sqlchat", broker=settings.broker_url, include=["app.tasks.db_config"])
celery_app.conf.update(
    broker_connection_timeout=3,
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.task_always_eager,
    task_ignore_result=True,
    task_publish_retry=False,
    task_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
)
