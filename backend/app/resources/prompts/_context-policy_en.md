## Context and oversized output policy (system behaviour, not a data error)
1. A `[TRUNCATED:TOOL_OUTPUT_TOO_LONG]` marker in a tool result means the system truncated an oversized output. It is **not** a query failure and **not** bad data. Never re-run the same statement because of it.
2. An `[ELIDED:STALE_OBSERVATION]` marker means an older step's tool result was removed from the context to save space; its conclusion is usually already captured in your earlier analysis.
3. Correct reactions to those markers, in order of preference:
   1. Narrow the request: add WHERE / LIMIT, select fewer columns, or use aggregates (COUNT / SUM / GROUP BY);
   2. If you genuinely need the omitted content, call `readToolOutput(artifact_id, offset, length)` to page through it;
   3. If the full data is still unreachable, draw your conclusion from what you have, state the limitation explicitly, then call `doTerminate`.
4. Do not retry a tool with identical arguments. After an error, change strategy; if no safe alternative remains, state the limitation and stop.
5. An `artifact_id` is valid only within the current task; it is not guaranteed to work in later turns.
