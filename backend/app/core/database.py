from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args: dict[str, object] = {}
if settings.database_url.startswith("postgresql"):
    connect_args["options"] = "-csearch_path=app"
elif settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def initialize_database() -> None:
    from app import models  # noqa: F401
    from app.services.bootstrap import bootstrap
    if settings.auto_create_schema:
        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        Base.metadata.create_all(engine)
    bootstrap()
