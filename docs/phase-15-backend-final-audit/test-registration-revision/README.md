# S15 registration assertion correction

Date: 2026-10-02. This bundle contains one test-only payload for root review. It does not alter the frozen candidate or the shared worktree.

## Review reason

The completed full backend regression reported two failures in `test_other_families_are_not_implicitly_registered[oracle/sqlserver]`. The test supplied S12-supported database types to `WorkflowSchema.register` and expected them to be rejected. The accepted S12 adapter registry and workflow explicitly support Oracle and SQL Server: the workflow uses Oracle's `oracle` dialect and SQL Server's `tsql` dialect, with SQL Server defaulting to `dbo`. The product migration matrix also lists both types and states that the ten adapter types are retained.

The negative assertion should target a type that is actually unknown. The payload changes only the final test in `backend/tests/test_mysql_family_workflow.py` to use `unsupported-test-database` and retain the explicit `ValueError` assertion. Existing MySQL-family schema, quote, typed-row, and wrong-value coverage remains byte-for-byte unchanged. No production code or existing S12 support test changes.

Positive S12 coverage already exists in the candidate's `backend/tests/test_native_workflow_bridge.py`: it checks all ten adapter registrations, Oracle's workflow dialect/namespace behavior, and SQL Server's `dbo` behavior. The targeted run below includes that existing test file to ensure the corrected negative test does not erase S12 support evidence.

## Evidence

The candidate `workflow_schema.py`, adapter `registry.py`, and `test_native_workflow_bridge.py` have the same SHA-256 values as their accepted `main-s14-combined-1790948846302` copies. The S12 README says that workflow selects `oracle`/`tsql` by service schema and SQL Server defaults to `dbo`. `spec/02-原项目功能对照与迁移边界.md` lists Oracle and SQL Server in the ten-database matrix.

Targeted pytest used the existing project Python from the accepted combined snapshot, imported application code from the frozen candidate, and ran the revised payload plus the candidate's existing native workflow bridge tests. Result: **42 passed, 0 failed**, exit code 0. See `targeted-pytest.log` and `targeted-pytest.json`. No full suite, real model, credentials, Docker command, or container lifecycle was used for this revision.

## Bundle boundary

`payload/backend/tests/test_mysql_family_workflow.py` is the only code payload. `baseline-hashes.json` records the candidate source and accepted S12 references. `test-registration-revision.diff` shows the only test change. `source-manifest.json` records the payload, documentation, and targeted evidence hashes. The candidate manifest SHA is retained in the manifest to bind this revision to `c-final-1628cf735dc5`.