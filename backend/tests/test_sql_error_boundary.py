"""Only known target statement diagnostics permit a bounded model correction."""

import pytest
from sqlalchemy.exc import DBAPIError

from app.agent.sql_errors import failure, repairable


class DriverError(Exception):
    def __init__(self, sqlstate: str | None = None, code: int | None = None) -> None:
        super().__init__(code, "diagnostic")
        self.sqlstate = sqlstate


@pytest.mark.parametrize("state,code,allowed", [
    ("42601", None, True), ("42P01", None, True), ("42703", None, True),
    ("42702", None, True), ("42803", None, True), ("42883", None, True),
    (None, 1052, True), (None, 1054, True), (None, 1064, True), (None, 1146, True),
    ("23505", None, False), ("08006", None, False), ("57014", None, False),
    ("42P04", None, False), (None, 1062, False), (None, 2006, False), (None, 2013, False),
])
def test_repairable_diagnostic_whitelist(state: str | None, code: int | None, allowed: bool) -> None:
    statement = "SELECT missing FROM records"
    error = DBAPIError(statement, {}, DriverError(state, code))
    assert repairable(error, statement) is allowed
    assert failure(error)["success"] is False


@pytest.mark.parametrize("boundary", ["invalidated", "rollback_failed", "system_statement", "no_statement"])
def test_known_diagnostic_is_not_enough_after_an_unsafe_boundary(boundary: str) -> None:
    statement = "INSERT INTO records (missing) VALUES (1)"
    actual = "SELECT app_secret FROM app.settings" if boundary == "system_statement" else statement
    error = DBAPIError(None if boundary == "no_statement" else actual, {}, DriverError("42703"),
                       connection_invalidated=boundary == "invalidated")
    if boundary == "rollback_failed":
        error.add_note("Rollback also failed: OperationalError")
    assert not repairable(error, statement)
