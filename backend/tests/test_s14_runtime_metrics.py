"""Live worker counters must reach the canonical API scrape, not a local registry."""

from __future__ import annotations

import pytest
from real_model_database import isolated_database
from sqlalchemy.exc import DBAPIError
from test_s14_runtime_support import Runtime, safe_live

pytest_plugins = ("test_s14_runtime_support",)



@safe_live
def test_real_worker_done_error_stale_reach_same_api(runtime: Runtime) -> None:
    published_before = runtime.metric("sqlchat_queue_publications_total", outcome="done")
    with isolated_database("postgresql", "test") as target:
        before = runtime.metric("sqlchat_verifications_total", outcome="done")
        identifier = runtime.create(target)
        done = runtime.completed(identifier)
        after_done = runtime.counter_after("done", before)
        assert done.status == 1 and done.document and not done.warning
        assert after_done - before == 1

        before_error = runtime.metric("sqlchat_verifications_total", outcome="error")
        error = runtime.completed(runtime.create(target, bad=True))
        after_error = runtime.counter_after("error", before_error)
        assert error.status == 2 and not error.document
        assert after_error - before_error == 1

        before_stale = runtime.metric("sqlchat_verifications_total", outcome="stale")
        runtime.stale(identifier)  # exact fresh ordinary-user config, previous version only
        after_stale = runtime.counter_after("stale", before_stale)
        assert runtime.state(identifier) == done
        assert after_stale - before_stale == 1
        assert runtime.metric("sqlchat_queue_publications_total", outcome="done") - published_before == 2

        snapshots = {outcome: runtime.metric("sqlchat_verifications_total", outcome=outcome)
                     for outcome in ("done", "partial", "stale", "error")}
        for _ in range(3):
            assert all(runtime.metric("sqlchat_verifications_total", outcome=outcome) == value
                       for outcome, value in snapshots.items())
        # Root's gateway only proxies /api. The alias is an explicit container
        # loopback request, never base_url /api accidentally concatenated twice.
        assert all(runtime.metric("sqlchat_verifications_total", direct=True, outcome=outcome) == value
                   for outcome, value in snapshots.items())
        runtime.report("worker_counters", {"passed": True, "final_image_checked": True,
                       "done_delta": 1, "error_delta": 1, "stale_delta": 1,
                       "api_publish_delta": 2, "stale_config_unchanged": True,
                       "repeat_scrape_stable": True, "direct_alias_matches": True})


@safe_live
def test_real_non_superuser_count_failure_remains_partial_and_observable(runtime: Runtime) -> None:
    with isolated_database("postgresql", "test") as target:
        with target.engine.begin() as connection:
            non_superuser = connection.exec_driver_sql(
                "SELECT NOT rolsuper FROM pg_roles WHERE rolname=current_user").scalar_one() is True
            assert non_superuser
            connection.exec_driver_sql('ALTER TABLE "orders" ENABLE ROW LEVEL SECURITY')
            connection.exec_driver_sql('ALTER TABLE "orders" FORCE ROW LEVEL SECURITY')
            connection.exec_driver_sql('CREATE POLICY s14_count_fault ON "orders" FOR SELECT USING (1 / 0 > 0)')
        actual_count_fault = False
        try:
            with target.engine.connect() as connection:
                connection.exec_driver_sql('SELECT COUNT(*) FROM "orders"')
        except DBAPIError as error:
            actual_count_fault = getattr(error.orig, "sqlstate", None) == "22012"
        if not actual_count_fault:
            runtime.report("partial_count_unverified", {"actual_count_fault": False, "passed": False})
            pytest.skip("Real COUNT fault not established; partial runtime remains unverified")
        before = runtime.metric("sqlchat_verifications_total", outcome="partial")
        state = runtime.completed(runtime.create(target))
        after = runtime.counter_after("partial", before)
        assert state.status == 1 and state.document and state.warning
        assert after - before == 1
        runtime.report("partial_count", {"passed": True, "non_superuser": True,
                       "actual_count_fault": True, "connected_status": 1,
                       "document_warning": True, "partial_delta": 1})
