from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_provider, get_session
from app.api.schemas import (
    DocumentCreate,
    DocumentDetail,
    DocumentSummary,
    EventView,
    ExtractionView,
)
from app.providers.base import ExtractionProvider
from app.repositories import documents as repo
from app.repositories.models import Document, Event, Extraction
from app.services.extraction import extract_document

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/documents", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED)
def create_document(
    body: DocumentCreate, session: Session = Depends(get_session)
) -> DocumentSummary:
    document = repo.create_document(session, filename=body.filename, source_text=body.text)
    return _summary(document)


@router.post("/documents/{document_id}/extract", response_model=ExtractionView)
def extract(
    document_id: str,
    session: Session = Depends(get_session),
    provider: ExtractionProvider = Depends(get_provider),
) -> ExtractionView:
    document = _require(session, document_id)
    outcome = extract_document(session, document, provider)
    return _extraction_view(outcome.extraction)


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def read_document(
    document_id: str, session: Session = Depends(get_session)
) -> DocumentDetail:
    document = _require(session, document_id)
    extraction = repo.latest_extraction(session, document_id)
    return DocumentDetail(
        **_summary(document).model_dump(),
        source_text=document.source_text,
        extraction=_extraction_view(extraction) if extraction else None,
        events=[_event_view(event) for event in repo.list_events(session, document_id)],
    )


def _require(session: Session, document_id: str) -> Document:
    document = repo.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return document


def _summary(document: Document) -> DocumentSummary:
    return DocumentSummary(id=document.id, filename=document.filename, status=document.status)


def _extraction_view(extraction: Extraction) -> ExtractionView:
    return ExtractionView(
        id=extraction.id,
        status=extraction.status,
        schema_version=extraction.schema_version,
        payload_hash=extraction.payload_hash,
        draft=extraction.draft,
        evidence=extraction.evidence or [],
        error_code=extraction.error_code,
        error_detail=extraction.error_detail,
        model=extraction.model,
        latency_ms=extraction.latency_ms,
    )


def _event_view(event: Event) -> EventView:
    return EventView(
        type=event.type,
        actor=event.actor,
        payload=event.payload,
        created_at=event.created_at.isoformat(),
    )
