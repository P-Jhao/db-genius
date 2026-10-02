from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import success
from app.core.observability_health import readiness
from app.core.observability_metrics import metrics_text

router = APIRouter()


@router.get("/health")
def health() -> dict[str, object]:
    return success({"status": "UP", "timestamp": datetime.now(UTC).isoformat()})


@router.get("/health/live")
def live() -> dict[str, object]:
    return success({"status": "UP"})


@router.get("/health/ready")
def ready() -> JSONResponse:
    checks = readiness(get_settings())
    if all(value == "UP" for value in checks.values()):
        return JSONResponse(content=success({"status": "UP", "checks": checks}))
    return JSONResponse(status_code=503, content={"code": 503, "message": "service not ready",
                                                  "data": {"status": "DOWN", "checks": checks}})


@router.get("/metrics")
def metrics() -> Response:
    payload, content_type = metrics_text()
    return Response(content=payload, media_type=content_type)
