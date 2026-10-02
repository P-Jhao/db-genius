from celery.signals import after_setup_logger, after_setup_task_logger

from app.core.config import get_settings
from app.core.observability_logging import configure_logging
from app.tasks.celery_app import celery_app


@after_setup_logger.connect
def configure_worker_logging(**_kwargs: object) -> None:
    configure_logging(get_settings())


@after_setup_task_logger.connect
def configure_worker_task_logging(**_kwargs: object) -> None:
    configure_logging(get_settings())


def main() -> None:
    celery_app.worker_main(["worker", "--loglevel=INFO", "--concurrency=2"])


if __name__ == "__main__":
    main()
