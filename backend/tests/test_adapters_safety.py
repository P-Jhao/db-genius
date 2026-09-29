import pytest

from app.adapters.safety import UnsafeStatement, check_statement


@pytest.mark.parametrize("dialect", ["mysql", "postgres"])
@pytest.mark.parametrize("statement", [
    "DROP TABLE t", "TRUNCATE TABLE t", "ALTER TABLE t DROP COLUMN c",
    "SELECT 1; DROP TABLE t", "SELECT 1; INSERT INTO t VALUES (1)",
    "WITH d AS (DELETE FROM t RETURNING id) SELECT * FROM d",
    "SELECT * INTO new_table FROM t", "EXPLAIN ANALYZE DELETE FROM t",
])
def test_forbidden_and_trial_writes(dialect: str, statement: str) -> None:
    with pytest.raises(UnsafeStatement):
        check_statement(statement, dialect, trial_mode=True)


@pytest.mark.parametrize("dialect", ["mysql", "postgres"])
def test_text_and_comment_do_not_trigger_drop_guard(dialect: str) -> None:
    for statement in ("SELECT 'DROP TABLE t' AS note", "SELECT 1 /* TRUNCATE t */ AS value",
                      "-- DROP TABLE t\nSELECT 1", "SELECT '/*!50000 DROP TABLE t */'"):
        assert check_statement(statement, dialect, trial_mode=True).read_only


@pytest.mark.parametrize("comment", ["/*!50000 DROP TABLE t */", "/*M!100000 DROP TABLE t */"])
def test_mysql_executable_comments_rejected(comment: str) -> None:
    with pytest.raises(UnsafeStatement):
        check_statement(f"SELECT 1 {comment}", "mysql", trial_mode=True)


@pytest.mark.parametrize("dialect", ["mysql", "postgres"])
def test_normal_writes_remain_available(dialect: str) -> None:
    for statement in ("CREATE TABLE sample (id INT)", "INSERT INTO sample VALUES (1)",
                      "UPDATE sample SET id = 2", "DELETE FROM sample WHERE id = 2"):
        assert not check_statement(statement, dialect).read_only
        with pytest.raises(UnsafeStatement):
            check_statement(statement, dialect, trial_mode=True)


def test_mysql_metadata_commands() -> None:
    for statement in ("SHOW TABLES", "SHOW COLUMNS FROM sample", "DESCRIBE sample",
                      "EXPLAIN SELECT * FROM sample"):
        assert check_statement(statement, "mysql", trial_mode=True).read_only


def test_postgresql_show_and_explain() -> None:
    assert check_statement("SHOW statement_timeout", "postgres", trial_mode=True).read_only
    assert check_statement("EXPLAIN SELECT * FROM sample", "postgres", trial_mode=True).read_only
    with pytest.raises(UnsafeStatement):
        check_statement("SHOW statement_timeout; DELETE FROM sample", "postgres", trial_mode=True)


@pytest.mark.parametrize("statement", ["CALL delete_everything()", "PREPARE x AS DROP TABLE t",
                                        "EXECUTE x", "SELECT 1; SELECT 2"])
def test_unclassified_or_multiple_statements_rejected(statement: str) -> None:
    with pytest.raises(UnsafeStatement):
        check_statement(statement, "postgres")
