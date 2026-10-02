from kombu import Connection
from sqlalchemy.engine import make_url

from deploy.connection_env import build_connection_urls


def test_special_characters_are_encoded_in_database_and_broker_urls() -> None:
    password = "p@ss:/word?with%reserved#chars"
    environment = {
        "POSTGRES_DB": "sqlchat",
        "POSTGRES_USER": "sqlchat@worker",
        "POSTGRES_PASSWORD": password,
        "RABBITMQ_DEFAULT_USER": "sqlchat/worker",
        "RABBITMQ_DEFAULT_PASS": password,
    }

    database_url, broker_url = build_connection_urls(environment)

    assert make_url(database_url).username == environment["POSTGRES_USER"]
    assert make_url(database_url).password == password
    broker = Connection(broker_url)
    assert broker.userid == environment["RABBITMQ_DEFAULT_USER"]
    assert broker.password == password
