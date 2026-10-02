from fastapi import APIRouter, Request

from app.api.auth import CurrentUser, DatabaseSession
from app.core.errors import success
from app.core.request_locale import locale_scope
from app.schemas.db_config import DbConfigRequest
from app.services import db_config as service

router = APIRouter(prefix="/db-config")


@router.post("")
def create(request: DbConfigRequest, http: Request, user: CurrentUser,
           session: DatabaseSession) -> dict[str, object]:
    with locale_scope(http.headers.get("accept-language")):
        return success(service.create_config(session, user.id, request).model_dump(by_alias=True))


@router.put("/{config_id}")
def update(config_id: int, request: DbConfigRequest, http: Request, user: CurrentUser,
           session: DatabaseSession) -> dict[str, object]:
    with locale_scope(http.headers.get("accept-language")):
        return success(service.update_config(session, user.id, config_id, request).model_dump(by_alias=True))


@router.delete("/{config_id}")
def delete(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    service.delete_config(session, user.id, config_id)
    return success()


@router.get("")
def list_configs(user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success([item.model_dump(by_alias=True) for item in service.list_configs(session, user.id)])


@router.get("/{config_id}")
def get(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.get_config(session, user.id, config_id).model_dump(by_alias=True))


@router.post("/{config_id}/test")
def test(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.test_connection(session, user.id, config_id))


@router.post("/{config_id}/generate-doc")
def generate_doc(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.generate_doc(session, user.id, config_id))


@router.post("/{config_id}/refresh-doc")
def refresh_doc(config_id: int, http: Request, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    with locale_scope(http.headers.get("accept-language")):
        return success(service.refresh_doc(session, user.id, config_id))


@router.get("/{config_id}/doc")
def get_doc(config_id: int, user: CurrentUser, session: DatabaseSession) -> dict[str, object]:
    return success(service.get_doc(session, user.id, config_id))
