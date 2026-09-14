from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    EXTRACTION_REQUESTED = "extraction_requested"
    EXTRACTION_SUCCEEDED = "extraction_succeeded"
    EXTRACTION_FAILED = "extraction_failed"
    EVIDENCE_VERIFIED = "evidence_verified"
    EVIDENCE_REJECTED = "evidence_rejected"
    VALIDATION_COMPLETED = "validation_completed"
    CORRECTION_APPLIED = "correction_applied"
    APPROVAL_GRANTED = "approval_granted"
    WRITE_ATTEMPTED = "write_attempted"
    WRITE_SUCCEEDED = "write_succeeded"
    WRITE_FAILED = "write_failed"


class DocumentStatus(StrEnum):
    RECEIVED = "received"
    EXTRACTED = "extracted"
    EXTRACTION_FAILED = "extraction_failed"
    NEEDS_REVIEW = "needs_review"


class ExtractionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
