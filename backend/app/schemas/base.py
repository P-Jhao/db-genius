from datetime import datetime

from pydantic import BaseModel, ConfigDict


def to_camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ResponseEnvelope[T](ApiModel):
    code: int = 200
    message: str = "success"
    data: T | None = None


class HealthData(ApiModel):
    status: str
    timestamp: datetime
