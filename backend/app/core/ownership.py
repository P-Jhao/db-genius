from typing import Protocol

from sqlalchemy.orm import Session

from app.core.errors import BusinessError


class UserOwned(Protocol):
    user_id: int


def require_owned[ResourceT: UserOwned](session: Session, model: type[ResourceT], resource_id: int,
                                       user_id: int, not_found_key: str) -> ResourceT:
    resource = session.get(model, resource_id)
    if resource is None or resource.user_id != user_id:
        raise BusinessError(404, not_found_key)
    return resource
