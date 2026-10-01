import logging
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.errors import BusinessError, deny_trial
from app.models import UploadedFile
from app.storage.backend import StorageLimitExceeded, get_storage
from app.storage.validation import DOC_EXTENSIONS, IMAGE_EXTENSIONS, MAX_FILE_SIZE, validate_content

CHUNK_SIZE = 1024 * 1024
logger = logging.getLogger(__name__)


def _extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def _upload_bytes(file: UploadFile) -> bytes:
    payload = bytearray()
    try:
        while chunk := file.file.read(CHUNK_SIZE):
            payload.extend(chunk)
            if len(payload) > MAX_FILE_SIZE:
                raise BusinessError(400, "error.file.tooLarge", 200, MAX_FILE_SIZE // CHUNK_SIZE)
    except BusinessError:
        raise
    except Exception as exc:
        raise BusinessError(500, "error.file.uploadFailed", 200, "unable to read upload") from exc
    if not payload:
        raise BusinessError(400, "error.file.empty")
    return bytes(payload)


def upload_file(session: Session, user_id: int, file: UploadFile) -> UploadedFile:
    deny_trial("error.trial.fileUpload")
    filename = file.filename
    extension = _extension(filename)
    if extension not in DOC_EXTENSIONS | IMAGE_EXTENSIONS:
        raise BusinessError(400, "error.file.typeNotAllowed", 200,
                            ", ".join(sorted(DOC_EXTENSIONS)), ", ".join(sorted(IMAGE_EXTENSIONS)))
    if filename is None or len(filename) > 256 or any(char in filename for char in "\x00\r\n/\\"):
        raise BusinessError(400, "Invalid upload filename")
    data = _upload_bytes(file)
    try:
        validate_content(extension, data)
    except ValueError as exc:
        raise BusinessError(400, "error.file.uploadFailed", 200, str(exc)) from exc
    try:
        storage = get_storage()
    except ValueError as exc:
        raise BusinessError(500, "error.file.uploadFailed", 200, "storage is not configured") from exc
    receipt = uuid4().hex
    key = f"uploads/{user_id}/{receipt}.{extension}"
    try:
        storage.put(key, data, file.content_type)
    except Exception as exc:
        raise BusinessError(500, "error.file.uploadFailed", 200, "storage unavailable") from exc
    record = UploadedFile(user_id=user_id, original_name=filename, oss_key=key,
                          file_size=len(data), content_type=file.content_type)
    try:
        session.add(record)
        session.flush()
    except Exception as exc:
        try:
            session.rollback()
        except Exception as rollback_exc:
            logger.error("upload receipt=%s user_id=%s extension=%s stage=flush_rollback_failed error_type=%s",
                         receipt, user_id, extension, type(rollback_exc).__name__)
            raise BusinessError(500, "error.file.uploadFailed", 200,
                                f"metadata save outcome needs reconciliation; reference {receipt}") from rollback_exc
        try:
            storage.delete(key)
        except Exception as cleanup_exc:
            logger.error("upload receipt=%s user_id=%s extension=%s stage=metadata_failed_cleanup_failed error_type=%s",
                         receipt, user_id, extension, type(cleanup_exc).__name__)
            raise BusinessError(500, "error.file.uploadFailed", 200,
                                f"metadata save and storage cleanup failed; reference {receipt}") from cleanup_exc
        raise BusinessError(500, "error.file.uploadFailed", 200, "metadata could not be saved") from exc
    try:
        session.commit()
    except Exception as exc:
        # A commit exception can arrive after the server committed. Retain the object
        # until a new connection can establish whether the metadata exists.
        logger.error("upload receipt=%s user_id=%s extension=%s stage=commit_outcome_unknown error_type=%s",
                     receipt, user_id, extension, type(exc).__name__)
        raise BusinessError(500, "error.file.uploadFailed", 200,
                            f"metadata commit outcome needs reconciliation; reference {receipt}") from exc
    try:
        session.refresh(record)
    except Exception as exc:
        logger.error("upload receipt=%s user_id=%s extension=%s stage=committed_confirmation_failed error_type=%s",
                     receipt, user_id, extension, type(exc).__name__)
        raise BusinessError(500, "error.file.uploadFailed", 200,
                            f"metadata was saved but confirmation failed; reference {receipt}") from exc
    return record


def read_owned_bytes(user_id: int, file_id: int, *, max_bytes: int | None = None) -> tuple[UploadedFile, bytes]:
    """Load a user's file by ID; callers never need a storage key or path."""
    limit = MAX_FILE_SIZE if max_bytes is None else max_bytes
    if limit < 0:
        raise ValueError("max_bytes must not be negative")
    with SessionLocal() as session:
        record = session.get(UploadedFile, file_id)
        if record is None:
            raise BusinessError(404, "error.file.notFound")
        if record.user_id != user_id:
            raise BusinessError(403, "error.file.noPermission")
        if not record.oss_key.startswith(f"uploads/{user_id}/"):
            raise BusinessError(403, "error.file.noPermission")
        if record.file_size is not None and record.file_size > limit:
            raise BusinessError(400, "File exceeds the read limit")
        try:
            storage = get_storage()
            data = storage.read(record.oss_key, limit)
        except StorageLimitExceeded as exc:
            raise BusinessError(400, "File exceeds the read limit") from exc
        except ValueError as exc:
            raise BusinessError(500, "File storage is not configured") from exc
        except Exception as exc:
            raise BusinessError(500, "File storage read failed") from exc
        if not data:
            raise BusinessError(500, "Stored file is empty")
        session.expunge(record)
        return record, data
