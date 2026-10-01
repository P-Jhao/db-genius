import sqlglot
from sqlglot import exp

from app.adapters.relational import RelationalAdapter


class PostgreSqlAdapter(RelationalAdapter):
    db_type = "postgresql"
    dialect = "postgres"
    driver = "postgresql+psycopg"
    default_port = 5432
    metadata_schema = "public"

    def _stream_results(self, statement: str, read_only: bool) -> bool:
        if not read_only:
            return False
        # PostgreSQL DECLARE accepts queries, but not SHOW or EXPLAIN commands.
        root = sqlglot.parse_one(statement, read=self.dialect)
        return isinstance(root, (exp.Select, exp.SetOperation))
