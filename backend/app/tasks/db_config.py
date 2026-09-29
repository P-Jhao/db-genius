from app.services.db_config_worker import verify_and_generate
from app.tasks.celery_app import celery_app


@celery_app.task(name="sqlchat.db_config.verify", time_limit=120)
def verify_config(config_id: int, version: int) -> None:
    verify_and_generate(config_id, version)
