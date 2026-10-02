"""Public trial mode status used before login."""

from fastapi import APIRouter

from app.core.errors import success
from app.services import trial

router = APIRouter(prefix="/trial")


@router.get("/status")
def status() -> dict[str, object]:
    return success(trial.status())
