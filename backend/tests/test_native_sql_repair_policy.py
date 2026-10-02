"""Native parse diagnostics are a small whitelist; uncertain operations stay fatal."""

from dataclasses import dataclass

import oracledb
import psycopg
import pymssql
import pymysql
import pytest
from sqlalchemy.exc import DBAPIError

from app.agent.sql_errors import failure, repairable


@dataclass
class OracleDetail:
    code: int
    full_code: str
    offset: int = 8
    stack: bool = False

    def __str__(self) -> str:
        return (self.full_code + ": simulated parse diagnostic"
                + ("\nORA-06512: function execution" if self.stack else ""))


def native_error(db_type: str, code: int, statement: str) -> DBAPIError:
    if db_type == "oracle":
        original = oracledb.DatabaseError(OracleDetail(code, f"ORA-{code:05d}"))
    elif db_type == "sqlserver":
        original = pymssql.ProgrammingError(code, b"simulated parse diagnostic")
    else:
        raise ValueError("Unknown fixture driver")
    return DBAPIError(statement, {}, original)


@pytest.mark.parametrize("db_type,code", [("oracle", code) for code in (904, 907, 923, 933, 936, 942, 3047)]
                         + [("sqlserver", code) for code in (102, 207, 208)])
def test_exact_native_driver_parse_diagnostic_is_repairable(db_type: str, code: int) -> None:
    statement = "SELECT missing FROM records"
    error = native_error(db_type, code, statement)
    assert repairable(error, statement) is True
    result = failure(error)
    assert result["success"] is False and result["errorCode"] == code
    assert "sqlState" not in result and result["error"]


@pytest.mark.parametrize("db_type,code", [("oracle", 942), ("sqlserver", 208)])
@pytest.mark.parametrize("condition", ["wrong_statement", "invalidated", "rollback_failed"])
def test_known_code_does_not_override_connection_or_rollback_facts(
    db_type: str, code: int, condition: str,
) -> None:
    statement = "SELECT name FROM records"
    error = native_error(db_type, code, "SELECT 1" if condition == "wrong_statement" else statement)
    if condition == "invalidated":
        error.connection_invalidated = True
    if condition == "rollback_failed":
        error.add_note("Rollback also failed: connection closed")
    assert repairable(error, statement) is False


@pytest.mark.parametrize("original", [
    oracledb.DatabaseError(OracleDetail(942, "ORA-00942", offset=0)),
    oracledb.DatabaseError(OracleDetail(942, "ORA-00942", stack=True)),
    oracledb.DatabaseError(OracleDetail(942, "DPY-4011")),
    oracledb.DatabaseError(OracleDetail(1013, "ORA-01013")),
    oracledb.DatabaseError(OracleDetail(1466, "ORA-01466")),
    oracledb.DatabaseError("ORA-00942: message alone is not evidence"),
    oracledb.InterfaceError(OracleDetail(942, "ORA-00942")),
    pymssql.OperationalError(208, b"wrong exception class"),
    pymssql.ProgrammingError(156, b"not whitelisted"),
    pymssql.ProgrammingError(2812, b"procedure missing"),
    pymssql.ProgrammingError(20003, b"timeout"),
    pymssql.ProgrammingError(20006, b"connection loss"),
    pymssql.ProgrammingError(1054, b"must not enter MySQL whitelist"),
    RuntimeError("ORA-00942: not the native driver"),
])
def test_native_unknown_network_timeout_and_message_only_errors_are_fatal(original: Exception) -> None:
    statement = "SELECT name FROM records"
    assert repairable(DBAPIError(statement, {}, original), statement) is False


@pytest.mark.parametrize("db_type,code", [("oracle", 942), ("sqlserver", 208)])
@pytest.mark.parametrize("statement", [
    "INSERT INTO records (name) VALUES ('Ada')", "UPDATE records SET name='Ada'",
    "DELETE FROM records", "CREATE TABLE records (id INTEGER)",
    "SELECT 1 INTO unwanted", "SELECT 1; SELECT 2",
])
def test_failed_native_dml_ddl_and_multi_statements_are_not_model_replayed(
    db_type: str, code: int, statement: str,
) -> None:
    assert repairable(native_error(db_type, code, statement), statement) is False


@pytest.mark.parametrize("db_type,statement", [
    ("oracle", "SELECT seq.NEXTVAL FROM DUAL"), ("oracle", 'SELECT seq."NEXTVAL" FROM DUAL'),
    ("oracle", 'WITH c AS (SELECT seq."NEXTVAL" AS value FROM DUAL) SELECT value FROM c'),
    ("oracle", "SELECT name FROM records FOR UPDATE"),
    ("sqlserver", "SELECT NEXT VALUE FOR seq"),
    ("sqlserver", "SELECT name FROM records WITH (UPDLOCK)"),
    ("sqlserver", "SELECT name FROM records WITH (XLOCK)"),
])
def test_sequence_and_locking_select_errors_are_not_model_replayed(db_type: str, statement: str) -> None:
    code = 942 if db_type == "oracle" else 208
    assert repairable(native_error(db_type, code, statement), statement) is False


@pytest.mark.parametrize("db_type,statement", [
    ("oracle", ("WITH c AS (SELECT 1 AS NEXTVAL FROM DUAL) SELECT c.NEXTVAL FROM c "
                "UNION ALL SELECT c.NEXTVAL FROM c")),
    ("sqlserver", "WITH c AS (SELECT 1 AS id) SELECT id FROM c UNION ALL SELECT id FROM c"),
])
def test_known_readonly_set_operation_keeps_the_repair_path(db_type: str, statement: str) -> None:
    code = 904 if db_type == "oracle" else 207
    assert repairable(native_error(db_type, code, statement), statement) is True


@pytest.mark.parametrize("original,allowed", [
    (psycopg.errors.UndefinedColumn("missing column"), True),
    (psycopg.errors.UndefinedTable("missing table"), True),
    (psycopg.errors.SyntaxError("syntax error"), True),
    (psycopg.errors.UniqueViolation("integrity failure"), False),
    (pymysql.err.ProgrammingError(1054, "unknown column"), True),
    (pymysql.err.ProgrammingError(1146, "missing table"), True),
    (pymysql.err.ProgrammingError(1064, "syntax error"), True),
    (pymysql.err.OperationalError(2013, "connection loss"), False),
])
def test_postgres_mysql_original_whitelist_and_failed_write_behavior_remain(
    original: Exception, allowed: bool,
) -> None:
    statement = "INSERT INTO records VALUES (1,'Ada')"
    assert repairable(DBAPIError(statement, {}, original), statement) is allowed
