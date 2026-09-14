from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

DEFAULT_APPROVAL_TTL = timedelta(minutes=30)


class ApprovalError(Exception):
    code = "approval_error"


class NotReadyForApproval(ApprovalError):
    code = "not_ready_for_approval"


class ExtractionSupersededError(ApprovalError):
    code = "extraction_superseded"


class ApprovalMissing(ApprovalError):
    code = "approval_missing"


class ApprovalExpired(ApprovalError):
    code = "approval_expired"


class AlreadyWritten(ApprovalError):
    code = "already_written"


def idempotency_key(document_id: str, payload_hash: str) -> str:
    digest = hashlib.sha256()
    for part in (document_id, payload_hash):
        digest.update(f"{len(part)}:{part}".encode())
    return digest.hexdigest()


def expiry_from(moment: datetime, ttl: timedelta = DEFAULT_APPROVAL_TTL) -> datetime:
    return moment + ttl


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
