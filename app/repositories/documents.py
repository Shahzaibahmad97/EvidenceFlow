from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.events import DocumentStatus, EventType
from app.domain.validation import RuleResult, normalize_supplier
from app.repositories.models import (
    Approval,
    CrmWrite,
    Document,
    Event,
    Extraction,
    ValidationResult,
)


def create_document(session: Session, *, filename: str, source_text: str) -> Document:
    document = Document(filename=filename, source_text=source_text)
    session.add(document)
    session.flush()
    return document


def list_documents(session: Session) -> list[Document]:
    return list(session.scalars(select(Document).order_by(Document.created_at, Document.id)))


def get_document(session: Session, document_id: str) -> Document | None:
    return session.get(Document, document_id)


def latest_extraction(session: Session, document_id: str) -> Extraction | None:
    stmt = (
        select(Extraction)
        .where(Extraction.document_id == document_id)
        .order_by(Extraction.created_at.desc(), Extraction.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_events(session: Session, document_id: str) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.document_id == document_id)
        .order_by(Event.created_at, Event.id)
    )
    return list(session.scalars(stmt))


def append_event(
    session: Session,
    *,
    document_id: str,
    type: EventType,
    actor: str,
    extraction_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Event:
    event = Event(
        document_id=document_id,
        extraction_id=extraction_id,
        type=type.value,
        actor=actor,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event


def known_invoice_numbers(session: Session, *, exclude_document_id: str) -> frozenset[tuple[str, str]]:
    """Supplier/number pairs already extracted from other documents."""
    stmt = (
        select(Extraction.draft)
        .where(
            Extraction.document_id != exclude_document_id,
            Extraction.draft.is_not(None),
        )
    )
    pairs = set()
    for draft in session.scalars(stmt):
        supplier = draft.get("supplier", {}).get("value", "")
        number = draft.get("invoice_number", {}).get("value", "")
        if supplier and number:
            pairs.add((normalize_supplier(supplier), number.strip()))
    return frozenset(pairs)


def record_validation(
    session: Session, *, extraction_id: str, results: Iterable[RuleResult]
) -> list[ValidationResult]:
    rows = [
        ValidationResult(
            extraction_id=extraction_id,
            rule=result.rule,
            outcome=result.outcome.value,
            message=result.message,
        )
        for result in results
    ]
    session.add_all(rows)
    session.flush()
    return rows


def list_validation_results(session: Session, extraction_id: str) -> list[ValidationResult]:
    stmt = (
        select(ValidationResult)
        .where(ValidationResult.extraction_id == extraction_id)
        .order_by(ValidationResult.created_at, ValidationResult.id)
    )
    return list(session.scalars(stmt))


def latest_approval(session: Session, document_id: str) -> Approval | None:
    stmt = (
        select(Approval)
        .where(Approval.document_id == document_id)
        .order_by(Approval.created_at.desc(), Approval.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def create_approval(
    session: Session,
    *,
    document_id: str,
    extraction_id: str,
    payload_hash: str,
    actor: str,
    expires_at: datetime,
) -> Approval:
    approval = Approval(
        document_id=document_id,
        extraction_id=extraction_id,
        payload_hash=payload_hash,
        actor=actor,
        expires_at=expires_at,
    )
    session.add(approval)
    session.flush()
    return approval


def find_write(session: Session, idempotency_key: str) -> CrmWrite | None:
    return session.scalars(
        select(CrmWrite).where(CrmWrite.idempotency_key == idempotency_key)
    ).first()


def claim_write(
    session: Session, *, document_id: str, extraction_id: str, idempotency_key: str
) -> tuple[CrmWrite, bool]:
    existing = find_write(session, idempotency_key)
    if existing is not None:
        return existing, False
    write = CrmWrite(
        document_id=document_id,
        extraction_id=extraction_id,
        idempotency_key=idempotency_key,
    )
    session.add(write)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return (
            session.scalars(
                select(CrmWrite).where(CrmWrite.idempotency_key == idempotency_key)
            ).one(),
            False,
        )
    return write, True


def mark_written(session: Session, *, document_id: str, payload_hash: str) -> bool:
    result = session.execute(
        update(Document)
        .where(
            Document.id == document_id,
            Document.status == DocumentStatus.APPROVED,
            Document.approved_payload_hash == payload_hash,
        )
        .values(status=DocumentStatus.WRITTEN)
    )
    return result.rowcount == 1
