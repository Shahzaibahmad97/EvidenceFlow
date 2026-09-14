from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.evidence import EvidenceResult, verify_draft
from app.domain.events import DocumentStatus, EventType, ExtractionStatus
from app.domain.schema import SCHEMA_VERSION, InvoiceDraft
from app.providers.base import ExtractionProvider, MalformedProviderOutput, ProviderError
from app.repositories import documents as repo
from app.repositories.models import Document, Extraction

SYSTEM_ACTOR = "system"


@dataclass(frozen=True)
class ExtractionOutcome:
    extraction: Extraction
    document: Document

    @property
    def succeeded(self) -> bool:
        return self.extraction.succeeded


def extract_document(
    session: Session, document: Document, provider: ExtractionProvider
) -> ExtractionOutcome:
    repo.append_event(
        session,
        document_id=document.id,
        type=EventType.EXTRACTION_REQUESTED,
        actor=SYSTEM_ACTOR,
        payload={"schema_version": SCHEMA_VERSION},
    )

    try:
        result = provider.extract(document.source_text)
    except ProviderError as exc:
        return _fail(session, document, code=exc.code, detail=str(exc))

    metadata = {
        "model": result.model,
        "prompt_hash": result.prompt_hash,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "request_id": result.request_id,
    }

    try:
        draft = InvoiceDraft.model_validate(result.raw)
    except ValidationError as exc:
        return _fail(
            session,
            document,
            code=MalformedProviderOutput.code,
            detail=_summarize(exc),
            raw_payload=result.raw,
            **metadata,
        )

    evidence = verify_draft(draft, document.source_text)
    extraction = _record(
        session,
        document,
        status=ExtractionStatus.SUCCEEDED,
        raw_payload=result.raw,
        draft=draft.model_dump(mode="json"),
        evidence=[item.to_row() for item in evidence],
        payload_hash=draft.payload_hash(),
        **metadata,
    )

    _record_evidence_events(session, document, extraction, evidence)

    document.status = DocumentStatus.EXTRACTED
    repo.append_event(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        type=EventType.EXTRACTION_SUCCEEDED,
        actor=SYSTEM_ACTOR,
        payload={
            "payload_hash": extraction.payload_hash,
            "unverified_fields": [item.field for item in evidence if not item.verified],
        },
    )
    return ExtractionOutcome(extraction=extraction, document=document)


def _record_evidence_events(
    session: Session,
    document: Document,
    extraction: Extraction,
    evidence: list[EvidenceResult],
) -> None:
    for event_type, verified in (
        (EventType.EVIDENCE_VERIFIED, True),
        (EventType.EVIDENCE_REJECTED, False),
    ):
        fields = [item.field for item in evidence if item.verified is verified]
        if fields:
            repo.append_event(
                session,
                document_id=document.id,
                extraction_id=extraction.id,
                type=event_type,
                actor=SYSTEM_ACTOR,
                payload={"fields": fields},
            )


def _fail(
    session: Session, document: Document, *, code: str, detail: str, **columns
) -> ExtractionOutcome:
    extraction = _record(
        session,
        document,
        status=ExtractionStatus.FAILED,
        error_code=code,
        error_detail=detail,
        **columns,
    )
    document.status = DocumentStatus.EXTRACTION_FAILED
    repo.append_event(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        type=EventType.EXTRACTION_FAILED,
        actor=SYSTEM_ACTOR,
        payload={"error_code": code, "error_detail": detail},
    )
    return ExtractionOutcome(extraction=extraction, document=document)


def _record(session: Session, document: Document, **columns) -> Extraction:
    extraction = Extraction(
        document_id=document.id, schema_version=SCHEMA_VERSION, **columns
    )
    session.add(extraction)
    session.flush()
    return extraction


def _summarize(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in error.errors()
    )
