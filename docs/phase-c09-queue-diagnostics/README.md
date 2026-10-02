# Queue diagnostics revision

Accepted base: `a4b36a64132f1c40f0610fb1697069d0b2e62eb1` (includes native `a0f17fe`). Root has not yet accepted this revision. The rejected candidate `queue-diagnostics-fix-b89cfafeeff24e988252aa1536ce182d` and its manifest remain immutable. Its 53-pass proof did not cover the two newly found defects; it is not acceptance proof for this revision.

The queue publish failure could store configured broker/system/checkpoint credentials and provider keys through `diagnostic(exc)`. Review also found two concrete failures in the rejected helper: Python dict `repr` can escape quotes/backslashes, so raw matching missed them and a regex terminated at the opposite quote; and the old common helper truncated at 1000 characters before sanitizing, exposing a truncated credential prefix. `rejected-probes.json` records both reproduced failures and corrected results using booleans/hashes only. It retains no plaintext diagnostic or actual credential.

New `core/diagnostics.py` uses only the standard library and accepted configuration/localization classes. Known raw, percent, quote_plus, repr and JSON escaped values are removed; arbitrary URI userinfo and named key/header values use properly paired quoted/escaped boundaries. `safe_exception_diagnostic` preserves the original class prefix and BusinessError locale/arguments, redacts the complete diagnostic, then applies the original 1000-character limit. This helper is for explicit diagnostic fields only, never business schema, comments, rows, prompts or model answers.

The service edit remains one import and one `_enqueue` diagnostic expression. Its fixed prefix, status/code/return False, commit, id/version/status predicate, and publish `args=(id, version)` with the original `locale` header are unchanged. All other service function ASTs match accepted; `_enqueue` matches after replacing only the diagnostic expression with a marker. `db_config_common.py`, C09 helpers, native/Oracle config-aware bridge, worker, task/header/locale logic, model parameters, main and dependencies remain accepted bytes/normalized content. Root and repo AGENTS.md were checked; no boundary or core directory change requires modification.

Final commands in `backend`, using the existing venv and no installation:

- `python -m ruff check app tests`: pass.
- `python -m mypy app`: pass, 96 source files.
- `python -m mypy --strict --follow-imports=silent app/core/diagnostics.py app/services/db_config.py tests/test_queue_diagnostics.py`: pass, 3 files.
- `python -m pytest tests/test_queue_diagnostics.py tests/test_db_config_partial.py tests/test_queue_locale.py -q --tb=short`: 92 passed, 0 skipped, 7.96s.

The final pytest session completed naturally and is recorded without rerunning an unchanged completed gate. `checks.json` records complete exit codes and tested source hashes. Tests use only synthetic credentials, mocked publishes and isolated SQLite; new cases cover paired quotes/backslashes, repr/JSON/header/query representations, secret truncation boundaries, ordinary long diagnostic caps, seven-language BusinessError translation/arguments, stale version, state, locale and task args. No real broker, worker, target database, provider, deployed image or Flash-model behavior is claimed; root owns those target windows.

Review `public-minimal.diff`, `revision.diff`, `guard.json`, `checks.json` and `rejected-probes.json`. All non-owned tracked files match the fresh accepted export after line-ending normalization; raw export and archive hashes are also recorded. Root can overlay the new helper/test and apply the small service diff to its latest accepted export before independent review. S14 will reuse this helper only after acceptance and will not add OpenTelemetry dependencies to this independent fix. The manifest freezes this candidate; any further finding requires a new revision.
