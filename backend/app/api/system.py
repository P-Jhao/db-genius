from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.errors import success

router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    return success({"status": "UP", "timestamp": datetime.now(UTC).isoformat()})
