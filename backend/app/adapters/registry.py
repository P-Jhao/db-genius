from app.adapters.mongodb import MongoDbAdapter
from app.adapters.mysql import MySqlAdapter
from app.adapters.mysql_family import (
    DorisAdapter,
    MariaDbAdapter,
    OceanBaseAdapter,
    StarRocksAdapter,
    TidbAdapter,
)
from app.adapters.oracle import OracleAdapter
from app.adapters.postgresql import PostgreSqlAdapter
from app.adapters.sqlserver import SqlServerAdapter
from app.adapters.types import DatabaseAdapter

_ADAPTERS: dict[str, DatabaseAdapter] = {
    "mysql": MySqlAdapter(),
    "postgresql": PostgreSqlAdapter(),
    "mariadb": MariaDbAdapter(),
    "tidb": TidbAdapter(),
    "doris": DorisAdapter(),
    "starrocks": StarRocksAdapter(),
    "oceanbase": OceanBaseAdapter(),
    "mongodb": MongoDbAdapter(),
    "oracle": OracleAdapter(),
    "sqlserver": SqlServerAdapter(),
}


def get_adapter(db_type: str) -> DatabaseAdapter:
    try:
        return _ADAPTERS[db_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported database type: {db_type}") from exc
