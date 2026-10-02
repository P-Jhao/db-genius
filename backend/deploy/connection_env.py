import os
import sys
from collections.abc import Mapping
from urllib.parse import quote

from sqlalchemy.engine import URL


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is missing")
    return value


def build_connection_urls(environment: Mapping[str, str]) -> tuple[str, str]:
    database_url = URL.create(
        "postgresql+psycopg",
        username=_required(environment, "POSTGRES_USER"),
        password=_required(environment, "POSTGRES_PASSWORD"),
        host="postgres",
        port=5432,
        database=_required(environment, "POSTGRES_DB"),
    ).render_as_string(hide_password=False)

    broker_user = quote(_required(environment, "RABBITMQ_DEFAULT_USER"), safe="")
    broker_password = quote(_required(environment, "RABBITMQ_DEFAULT_PASS"), safe="")
    broker_url = f"amqp://{broker_user}:{broker_password}@rabbitmq:5672//"
    return database_url, broker_url


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("A command is required")
    database_url, broker_url = build_connection_urls(os.environ)
    os.environ["SQLCHAT_DATABASE_URL"] = database_url
    os.environ["SQLCHAT_BROKER_URL"] = broker_url
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)


if __name__ == "__main__":
    main()
