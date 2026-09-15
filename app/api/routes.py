from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_actor, get_crm, get_provider, get_session
from app.api.schemas import (
    ApprovalView,
    DocumentCreate,
    DocumentDetail,
    DocumentSummary,
    EventView,
    ExtractionView,
    JobCreate,
    JobView,
    ValidationView,
    WriteView,
)
from app.api.errors import as_http_error, commit_refusal
from app.domain.approval import ApprovalError
from app.domain.jobs import JobType
from app.providers.base import ExtractionProvider
from app.providers.crm import CrmClient, CrmError
from app.repositories import documents as repo
from app.repositories.models import (
    Approval,
    Document,
    Job,
    Event,
    Extraction,
    ValidationResult,
)
from app.services.approval import approve_extraction
from app.services.crm_write import write_approved_record
from app.services.extraction import extract_document
from app.services.validation import validate_extraction
from app.workflows import queue

router = APIRouter()


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/review", status_code=status.HTTP_302_FOUND)


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(session: Session = Depends(get_session)) -> list[DocumentSummary]:
    return [_summary(document) for document in repo.list_documents(session)]


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


@router.post("/documents/{document_id}/approve", response_model=ApprovalView)
def approve(
    document_id: str,
    session: Session = Depends(get_session),
    actor: str = Depends(get_actor),
) -> ApprovalView:
    document = _require(session, document_id)
    extraction = repo.latest_extraction(session, document_id)
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="nothing to approve")
    try:
        approval = approve_extraction(session, document, extraction, actor=actor)
    except ApprovalError as exc:
        raise as_http_error(commit_refusal(session, exc)) from exc
    return _approval_view(approval)


@router.post("/documents/{document_id}/write", response_model=WriteView)
def write(
    document_id: str,
    session: Session = Depends(get_session),
    crm: CrmClient = Depends(get_crm),
) -> WriteView:
    document = _require(session, document_id)
    try:
        outcome = write_approved_record(session, document, crm)
    except ApprovalError as exc:
        raise as_http_error(commit_refusal(session, exc)) from exc
    except CrmError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    return WriteView(
        idempotency_key=outcome.write.idempotency_key,
        status=outcome.write.status,
        external_id=outcome.external_id,
        attempts=outcome.write.attempts,
        called_destination=outcome.called_destination,
    )


@router.post(
    "/documents/{document_id}/jobs",
    response_model=JobView,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_job(
    document_id: str, body: JobCreate, session: Session = Depends(get_session)
) -> JobView:
    _require(session, document_id)
    try:
        job_type = JobType(body.type)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"unknown job type {body.type}"
        ) from exc
    return _job_view(queue.enqueue(session, type=job_type, document_id=document_id))


@router.get("/jobs/review", response_model=list[JobView])
def review_queue(session: Session = Depends(get_session)) -> list[JobView]:
    return [_job_view(job) for job in queue.review_queue(session)]


@router.get("/jobs/{job_id}", response_model=JobView)
def read_job(job_id: str, session: Session = Depends(get_session)) -> JobView:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return _job_view(job)


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
        approval=_approval_view(approval) if (approval := repo.latest_approval(session, document_id)) else None,
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


def _job_view(job: Job) -> JobView:
    return JobView(
        id=job.id,
        type=job.type,
        document_id=job.document_id,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        run_at=job.run_at.isoformat(),
        failure_kind=job.failure_kind,
        last_error=job.last_error,
    )


def _approval_view(approval: Approval) -> ApprovalView:
    return ApprovalView(
        id=approval.id,
        extraction_id=approval.extraction_id,
        payload_hash=approval.payload_hash,
        actor=approval.actor,
        expires_at=approval.expires_at.isoformat(),
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
