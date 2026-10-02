from celery import Celery  # type: ignore[import-untyped]
from celery.signals import (  # type: ignore[import-untyped]
    after_setup_logger,
    after_setup_task_logger,
    before_task_publish,
    worker_process_init,
    worker_process_shutdown,
    worker_shutdown,
)

from app.core.config import get_settings
from app.core.observability_logging import configure_logging
from app.core.observability_multiprocess import close_metrics, start_metrics
from app.core.observability_tracing import configure_tracing, flush_tracing, inject_headers

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
    control_queue_durable=True,
    event_queue_durable=True,
)


def propagate_task_context(sender: str | None = None, headers: dict[str, object] | None = None,
                           **_kwargs: object) -> None:
    if sender == "sqlchat.db_config.verify" and headers is not None:
        inject_headers(headers)


def setup_worker_logging(**_kwargs: object) -> None:
    start_metrics(get_settings(), service="worker")
    configure_logging(get_settings())


def setup_worker_tracing(**_kwargs: object) -> None:
    start_metrics(get_settings(), service="worker")
    configure_logging(get_settings())
    configure_tracing(get_settings(), service_name="sqlchat-worker")


def flush_worker_tracing(**_kwargs: object) -> None:
    try:
        flush_tracing()
    finally:
        close_metrics()


before_task_publish.connect(propagate_task_context, weak=False)
after_setup_logger.connect(setup_worker_logging, weak=False)
after_setup_task_logger.connect(setup_worker_logging, weak=False)
worker_process_init.connect(setup_worker_tracing, weak=False)
worker_shutdown.connect(flush_worker_tracing, weak=False)
worker_process_shutdown.connect(flush_worker_tracing, weak=False)
