from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.domain.approval import (
    AlreadyWritten,
    ApprovalExpired,
    ApprovalMissing,
    ExtractionSupersededError,
    as_utc,
    idempotency_key,
    now,
)
from app.domain.events import DocumentStatus, EventType, WriteStatus
from app.providers.crm import CrmClient, CrmError
from app.repositories import documents as repo
from app.repositories.models import CrmWrite, Document

SYSTEM_ACTOR = "system"


@dataclass(frozen=True)
class WriteOutcome:
    write: CrmWrite
    called_destination: bool

    @property
    def external_id(self) -> str | None:
        return self.write.external_id


def write_approved_record(session: Session, document: Document, crm: CrmClient) -> WriteOutcome:
    if document.approved_payload_hash is None:
        raise ApprovalMissing("no approval recorded for the current version")

    key = idempotency_key(document.id, document.approved_payload_hash)
    settled = repo.find_write(session, key)
    if settled is not None and settled.status == WriteStatus.SUCCEEDED:
        if document.status != DocumentStatus.WRITTEN:
            raise AlreadyWritten(f"record {settled.external_id} already exists for this version")
        return WriteOutcome(write=settled, called_destination=False)

    approval = repo.latest_approval(session, document.id)
    if approval is None or approval.payload_hash != document.approved_payload_hash:
        raise ApprovalMissing("no approval matches the current version")
    expires_at = as_utc(approval.expires_at)
    if expires_at <= now():
        raise ApprovalExpired(f"approval expired at {expires_at.isoformat()}")

    extraction = repo.latest_extraction(session, document.id)
    if extraction is None or extraction.payload_hash != approval.payload_hash:
        raise ExtractionSupersededError("the document changed after approval")

    write, claimed = repo.claim_write(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        idempotency_key=key,
    )

    repo.append_event(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        type=EventType.WRITE_ATTEMPTED,
        actor=SYSTEM_ACTOR,
        payload={"idempotency_key": key, "attempt": write.attempts + 1, "claimed": claimed},
    )
    write.attempts += 1

    try:
        record = crm.create_record(key, extraction.draft)
    except CrmError as exc:
        write.status = WriteStatus.FAILED
        write.last_error = f"{exc.code}: {exc}"
        repo.append_event(
            session,
            document_id=document.id,
            extraction_id=extraction.id,
            type=EventType.WRITE_FAILED,
            actor=SYSTEM_ACTOR,
            payload={"idempotency_key": key, "error_code": exc.code, "error": str(exc)},
        )
        raise

    write.status = WriteStatus.SUCCEEDED
    write.external_id = record.external_id
    write.last_error = None

    if not repo.mark_written(session, document_id=document.id, payload_hash=approval.payload_hash):
        raise ExtractionSupersededError("document left the approved state before the write landed")

    repo.append_event(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        type=EventType.WRITE_SUCCEEDED,
        actor=SYSTEM_ACTOR,
        payload={
            "idempotency_key": key,
            "external_id": record.external_id,
            "created_at_destination": record.created,
        },
    )
    return WriteOutcome(write=write, called_destination=True)
