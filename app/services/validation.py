from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.evidence import EvidenceResult
from app.domain.events import DocumentStatus, EventType
from app.domain.schema import InvoiceDraft
from app.domain.validation import RuleResult, ValidationInput, is_accepted, validate
from app.repositories import documents as repo
from app.repositories.models import Document, Extraction
from app.services.extraction import SYSTEM_ACTOR


def validate_extraction(
    session: Session, document: Document, extraction: Extraction
) -> list[RuleResult]:
    """Run the deterministic rules over a successful extraction and route the document."""
    results = validate(
        ValidationInput(
            draft=InvoiceDraft.model_validate(extraction.draft),
            source=document.source_text,
            evidence=[EvidenceResult.from_row(row) for row in extraction.evidence or []],
            known_invoice_numbers=repo.known_invoice_numbers(
                session, exclude_document_id=document.id
            ),
        )
    )
    repo.record_validation(session, extraction_id=extraction.id, results=results)

    accepted = is_accepted(results)
    document.status = DocumentStatus.VALIDATED if accepted else DocumentStatus.NEEDS_REVIEW
    repo.append_event(
        session,
        document_id=document.id,
        extraction_id=extraction.id,
        type=EventType.VALIDATION_COMPLETED,
        actor=SYSTEM_ACTOR,
        payload={
            "accepted": accepted,
            "blocking": [
                {"rule": r.rule, "outcome": r.outcome.value, "message": r.message}
                for r in results
                if r.blocking
            ],
        },
    )
    return results
