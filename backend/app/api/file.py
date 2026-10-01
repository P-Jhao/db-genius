from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.auth import CurrentUser, DatabaseSession
from app.core.errors import success
from app.schemas.uploaded_file import UploadedFileVO
from app.services.file_upload import upload_file

router = APIRouter(prefix="/file")


@router.post("/upload")
def upload(file: Annotated[UploadFile, File()], user: CurrentUser,
           session: DatabaseSession) -> dict[str, object]:
    uploaded = upload_file(session, user.id, file)
    return success(UploadedFileVO.from_entity(uploaded).model_dump(by_alias=True))
