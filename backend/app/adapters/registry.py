from app.adapters.mysql import MySqlAdapter
from app.adapters.postgresql import PostgreSqlAdapter
from app.adapters.relational import RelationalAdapter

_ADAPTERS: dict[str, RelationalAdapter] = {
    "mysql": MySqlAdapter(),
    "postgresql": PostgreSqlAdapter(),
}


def get_adapter(db_type: str) -> RelationalAdapter:
    try:
        return _ADAPTERS[db_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported database type: {db_type}") from exc
