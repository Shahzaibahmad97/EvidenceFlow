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
    ValidationView,
)
from app.providers.base import ExtractionProvider
from app.repositories import documents as repo
from app.repositories.models import Document, Event, Extraction, ValidationResult
from app.services.extraction import extract_document
from app.services.validation import validate_extraction

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
    if outcome.succeeded:
        validate_extraction(session, document, outcome.extraction)
    return _extraction_view(session, outcome.extraction)


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def read_document(
    document_id: str, session: Session = Depends(get_session)
) -> DocumentDetail:
    document = _require(session, document_id)
    extraction = repo.latest_extraction(session, document_id)
    return DocumentDetail(
        **_summary(document).model_dump(),
        source_text=document.source_text,
        extraction=_extraction_view(session, extraction) if extraction else None,
        events=[_event_view(event) for event in repo.list_events(session, document_id)],
    )


def _require(session: Session, document_id: str) -> Document:
    document = repo.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return document


def _summary(document: Document) -> DocumentSummary:
    return DocumentSummary(id=document.id, filename=document.filename, status=document.status)


def _extraction_view(session: Session, extraction: Extraction) -> ExtractionView:
    validation = repo.list_validation_results(session, extraction.id)
    return ExtractionView(
        validation=[_validation_view(row) for row in validation],
        accepted=all(row.outcome == "pass" for row in validation) if validation else None,
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


def _validation_view(row: ValidationResult) -> ValidationView:
    return ValidationView(rule=row.rule, outcome=row.outcome, message=row.message)


def _event_view(event: Event) -> EventView:
    return EventView(
        type=event.type,
        actor=event.actor,
        payload=event.payload,
        created_at=event.created_at.isoformat(),
    )
