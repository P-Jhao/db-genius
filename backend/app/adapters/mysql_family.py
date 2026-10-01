"""Explicit MySQL-wire adapters; server capabilities differ from MySQL."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from app.adapters.relational import RelationalAdapter
from app.adapters.types import DbConnectionConfig, SchemaMetadata


class MysqlFamilyAdapter(RelationalAdapter):
    dialect = "mysql"
    driver = "mysql+pymysql"
    mysql_protocol = True
    timeout_variable: str
    timeout_multiplier: int = 1
    trial_transaction = False
    safe_control_kill = False

    def _set_timeout(self, connection: Connection, timeout_seconds: int, trial_mode: bool) -> None:
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        connection.exec_driver_sql(
            f"SET SESSION {self.timeout_variable} = {timeout_seconds * self.timeout_multiplier}"
        )
        if trial_mode and self.trial_transaction:
            connection.exec_driver_sql("START TRANSACTION READ ONLY")

    def _cancel_running_statement(
        self, config: DbConnectionConfig, connection: Connection, connection_id: int | None
    ) -> None:
        if not self.safe_control_kill:
            raise RuntimeError(
                f"{self.db_type} cannot safely cancel by connection ID through an unpinned proxy; "
                "driver and server timeouts remain active"
            )
        super()._cancel_running_statement(config, connection, connection_id)


class MariaDbAdapter(MysqlFamilyAdapter):
    db_type = "mariadb"
    default_port = 3306
    timeout_variable = "max_statement_time"
    trial_transaction = True
    safe_control_kill = True


class TidbAdapter(MysqlFamilyAdapter):
    db_type = "tidb"
    default_port = 4000
    timeout_variable = "max_execution_time"
    timeout_multiplier = 1000


class OceanBaseAdapter(MysqlFamilyAdapter):
    """Only OceanBase MySQL-mode tenants using the MySQL wire protocol."""

    db_type = "oceanbase"
    default_port = 2881
    timeout_variable = "ob_query_timeout"
    timeout_multiplier = 1_000_000


class OlapMysqlAdapter(MysqlFamilyAdapter):
    """FE endpoint metadata is read from information_schema, not MySQL reflection."""

    default_port = 9030
    timeout_variable = "query_timeout"
    index_metadata_supported = True

    def extract_metadata(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> SchemaMetadata:
        from app.adapters.mysql_family_metadata import extract_olap_metadata

        return extract_olap_metadata(self, config, timeout_seconds)


class DorisAdapter(OlapMysqlAdapter):
    db_type = "doris"


class StarRocksAdapter(OlapMysqlAdapter):
    db_type = "starrocks"
    # information_schema.STATISTICS is a documented placeholder, not an empty index list.
    index_metadata_supported = False
