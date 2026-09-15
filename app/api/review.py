from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.dependencies import get_actor, get_crm, get_session
from app.api.highlight import segments
from app.api.errors import commit_refusal
from app.domain.approval import ApprovalError, idempotency_key
from app.domain.schema import InvoiceDraft
from app.providers.crm import CrmClient, CrmError
from app.repositories import documents as repo
from app.repositories.models import Document, Event, Extraction
from app.services.approval import approve_extraction
from app.services.crm_write import write_approved_record

router = APIRouter(prefix="/review", include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

SUMMARY_KEYS = (
    "external_id",
    "error_code",
    "payload_hash",
    "unverified_fields",
    "idempotency_key",
    "fields",
    "blocking",
)


@router.get("")
def queue(request: Request, session: Session = Depends(get_session)):
    rows = []
    for document in repo.list_documents(session):
        extraction = repo.latest_extraction(session, document.id)
        rows.append(
            {
                "id": document.id,
                "filename": document.filename,
                "status": document.status,
                "blocking": _blocking(session, extraction),
                "external_id": _external_id(session, document),
            }
        )
    return templates.TemplateResponse(request, "queue.html", {"documents": rows})


@router.get("/{document_id}")
def detail(
    document_id: str, request: Request, session: Session = Depends(get_session), message: str = ""
):
    document = _require(session, document_id)
    extraction = repo.latest_extraction(session, document_id)
    draft = extraction.draft if extraction and extraction.succeeded else None
    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "document": document,
            "extraction": extraction,
            "fields": _summary_fields(draft),
            "segments": segments(document.source_text, (extraction.evidence if extraction else None) or []),
            "validation": repo.list_validation_results(session, extraction.id) if extraction else [],
            "events": [_event(event) for event in repo.list_events(session, document_id)],
            "external_id": _external_id(session, document),
            "message": message,
        },
    )


@router.post("/{document_id}/approve")
def approve(
    document_id: str,
    payload_hash: str = Form(...),
    session: Session = Depends(get_session),
    actor: str = Depends(get_actor),
):
    document = _require(session, document_id)
    extraction = repo.latest_extraction(session, document_id)
    if extraction is None or extraction.payload_hash != payload_hash:
        return _back(document_id, "The document changed since this page was loaded. Reload and read it again.")
    try:
        approve_extraction(session, document, extraction, actor=actor)
    except ApprovalError as exc:
        return _back(document_id, str(commit_refusal(session, exc)))
    return _back(document_id, f"Approved by {actor}.")


@router.post("/{document_id}/write")
def write(
    document_id: str,
    session: Session = Depends(get_session),
    crm: CrmClient = Depends(get_crm),
):
    document = _require(session, document_id)
    try:
        outcome = write_approved_record(session, document, crm)
    except ApprovalError as exc:
        return _back(document_id, str(commit_refusal(session, exc)))
    except CrmError as exc:
        return _back(document_id, str(exc))
    verb = "Wrote" if outcome.called_destination else "Already written as"
    return _back(document_id, f"{verb} {outcome.external_id}.")


def _back(document_id: str, message: str) -> RedirectResponse:
    return RedirectResponse(
        f"/review/{document_id}?message={message}", status_code=status.HTTP_303_SEE_OTHER
    )


def _require(session: Session, document_id: str) -> Document:
    document = repo.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
    return document


def _blocking(session: Session, extraction: Extraction | None) -> list[str]:
    if extraction is None:
        return []
    return [
        row.rule
        for row in repo.list_validation_results(session, extraction.id)
        if row.outcome != "pass"
    ]


def _external_id(session: Session, document: Document) -> str | None:
    if document.approved_payload_hash is None:
        return None
    write = repo.find_write(session, idempotency_key(document.id, document.approved_payload_hash))
    return write.external_id if write else None


def _summary_fields(draft: dict[str, Any] | None) -> list[tuple[str, str]]:
    if draft is None:
        return []
    parsed = InvoiceDraft.model_validate(draft)
    fields = [(name, str(field.value)) for name, field in parsed.evidenced_fields().items()]
    fields.append(("line items", str(len(parsed.line_items))))
    return fields


def _event(event: Event) -> dict[str, str]:
    detail = {key: event.payload[key] for key in SUMMARY_KEYS if key in event.payload}
    return {
        "type": event.type,
        "actor": event.actor,
        "summary": json.dumps(detail, default=str)[:160] if detail else "",
    }
