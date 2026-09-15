from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.domain.approval import ApprovalError, ApprovalMissing


def commit_refusal(session: Session, error: ApprovalError) -> ApprovalError:
    """A refusal is a recorded outcome: commit it before the exception unwinds."""
    session.commit()
    return error


def as_http_error(error: ApprovalError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, ApprovalMissing)
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(
        status_code=code, detail={"code": error.code, "message": str(error)}
    )
