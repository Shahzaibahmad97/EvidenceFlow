from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.events import EventType
from app.repositories.models import Document, Event, Extraction


def create_document(session: Session, *, filename: str, source_text: str) -> Document:
    document = Document(filename=filename, source_text=source_text)
    session.add(document)
    session.flush()
    return document


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
