from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine() -> Engine:
    url = get_settings().database_url
    connect_args: dict[str, object] = {}
    if url.startswith("postgresql"):
        connect_args["options"] = "-csearch_path=app"
    elif url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        raise ValueError("System database must be PostgreSQL or an explicit SQLite test database")
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False)
