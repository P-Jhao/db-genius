from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.db_config import router as db_config_router
from app.api.model_config import router as model_config_router
from app.api.system import router as system_router
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import BusinessError
from app.core.localization import translate
from app.services.db_config_init import initialize_trial_database
from app.services.model_config import initialize_providers


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    with SessionLocal() as session:
        initialize_providers(session)
        initialize_trial_database(session)
    yield


app = FastAPI(title="SQLChat", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, error: BusinessError) -> JSONResponse:
    message = translate(error.message, request.headers.get("accept-language"), *error.message_args)
    return JSONResponse(
        status_code=error.status_code,
        content={"code": error.code, "message": message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    details = "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    )
    return JSONResponse(status_code=400, content={"code": 400, "message": details, "data": None})


app.include_router(system_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(db_config_router, prefix="/api")
app.include_router(model_config_router, prefix="/api")
