from app.adapters.relational import RelationalAdapter


class PostgreSqlAdapter(RelationalAdapter):
    db_type = "postgresql"
    dialect = "postgres"
    driver = "postgresql+psycopg"
    default_port = 5432
    metadata_schema = "public"
