from __future__ import annotations

from datetime import timedelta
from enum import StrEnum

from app.domain.approval import ApprovalError
from app.providers.base import ProviderError, ProviderTimeout
from app.providers.crm import CrmError, CrmUnavailable

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_BACKOFF = timedelta(seconds=2)
DEFAULT_LEASE = timedelta(seconds=60)


class JobType(StrEnum):
    EXTRACT = "extract"
    WRITE = "write"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FailureKind(StrEnum):
    TRANSIENT_EXHAUSTED = "transient_exhausted"
    PERMANENT = "permanent"


TRANSIENT_ERRORS = (ProviderTimeout, CrmUnavailable)
PERMANENT_ERRORS = (ProviderError, CrmError, ApprovalError)


def is_transient(error: Exception) -> bool:
    if isinstance(error, TRANSIENT_ERRORS):
        return True
    if isinstance(error, PERMANENT_ERRORS):
        return False
    return False


def backoff(attempts: int, base: timedelta = DEFAULT_BASE_BACKOFF) -> timedelta:
    return base * (2 ** max(attempts - 1, 0))
