"""Trial status and intent limits shared by HTTP and graph routing."""

from app.agent.types import Intent
from app.core.config import get_settings
from app.core.errors import deny_trial


def status() -> dict[str, bool]:
    return {"trialEnabled": get_settings().trial_enabled}


def require_intent_available(intent: Intent | None) -> None:
    if intent == "workflow":
        deny_trial("error.trial.workflow")
    elif intent == "db_compare":
        deny_trial("error.trial.dbCompare")
