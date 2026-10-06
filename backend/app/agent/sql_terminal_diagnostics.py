"""SQL completion diagnostics containing state flags and counts only."""

import json
import logging
from typing import Literal

from app.agent.tools import RunTools

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
TerminalPath = Literal["direct", "terminate", "step_limit", "loop_stop"]


def observe_completion(tools: RunTools, terminal_path: TerminalPath,
                       override_applied: bool) -> None:
    goal = tools.task_goal
    if goal is None:
        raise RuntimeError("SQL terminal diagnostics require an analyzed task goal")
    logger.info("SQL completion " + json.dumps({
        "taskId": tools.task_id,
        "taskGoalMode": goal.mode,
        "terminalPath": terminal_path,
        "overrideApplied": override_applied,
        "schemaEvidenceComplete": tools.schema_evidence.status(goal)["complete"],
        "statementsAttempted": tools.statements_attempted,
        "statementsExecuted": tools.statements_executed,
    }, sort_keys=True))
