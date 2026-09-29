from fastapi import APIRouter

from app.api.auth import CurrentUser, DatabaseSession
from app.core.errors import deny_trial, success
from app.schemas.model_config import ContextWindowLookupRequest, UserModelConfigRequest, UserModelConfigUpdate
from app.services import model_config as service
from app.services.model_config_info import lookup_context_window

router = APIRouter(prefix="/model-config")


@router.get("/providers")
def providers(user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success([item.model_dump(by_alias=True) for item in service.list_providers(session)])


@router.get("/configs")
def configs(user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success([item.model_dump(by_alias=True) for item in service.list_configs(session, user.id)])


@router.post("/configs")
def create(request: UserModelConfigRequest, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.create_config(session, user.id, request).model_dump(by_alias=True))


@router.put("/configs/{config_id}")
def update(config_id: int, request: UserModelConfigUpdate,
           user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.update_config(session, user.id, config_id, request).model_dump(by_alias=True))


@router.delete("/configs/{config_id}")
def delete(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    service.delete_config(session, user.id, config_id)
    return success()


@router.put("/configs/{config_id}/default")
def set_default(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    service.set_default(session, user.id, config_id)
    return success()


@router.get("/active")
def active(user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.active_config_vo(session, user.id).model_dump(by_alias=True))


@router.post("/context-window/lookup")
def lookup(request: ContextWindowLookupRequest, user: CurrentUser) -> dict[str, object]:
    deny_trial("error.trial.contextWindowLookup")
    return success(lookup_context_window(request.base_url, request.api_key,
                                         request.model_name).model_dump(by_alias=True))


@router.get("/configs/{config_id}/context-window")
def lookup_saved(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.saved_context_window(session, user.id, config_id).model_dump(by_alias=True))
