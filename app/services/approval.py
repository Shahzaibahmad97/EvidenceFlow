from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.domain.approval import (
    DEFAULT_APPROVAL_TTL,
    ExtractionSupersededError,
    NotReadyForApproval,
    expiry_from,
    now,
)
from app.domain.events import DocumentStatus, EventType
from app.repositories import documents as repo
from app.repositories.models import Approval, Document, Extraction
from app.services.validation import validate_extraction


def approve_extraction(
    session: Session,
    document: Document,
    extraction: Extraction,
    *,
    actor: str,
    ttl: timedelta = DEFAULT_APPROVAL_TTL,
) -> Approval:
    if document.status != DocumentStatus.VALIDATED:
        raise NotReadyForApproval(f"document is {document.status}, not validated")

    current = repo.latest_extraction(session, document.id)
    if current is None or current.id != extraction.id:
        raise ExtractionSupersededError("a newer extraction exists for this document")

    blocking = [result for result in validate_extraction(session, document, extraction) if result.blocking]
    if blocking:
        document.status = DocumentStatus.NEEDS_REVIEW
        raise NotReadyForApproval(
            "; ".join(f"{result.rule}: {result.message}" for result in blocking)
        )

    approval = repo.create_approval(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        payload_hash=extraction.payload_hash,
        actor=actor,
        expires_at=expiry_from(now(), ttl),
    )
    document.status = DocumentStatus.APPROVED
    document.approved_payload_hash = extraction.payload_hash

    repo.append_event(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        type=EventType.APPROVAL_GRANTED,
        actor=actor,
        payload={
            "approval_id": approval.id,
            "payload_hash": approval.payload_hash,
            "expires_at": approval.expires_at.isoformat(),
        },
    )
    return approval
