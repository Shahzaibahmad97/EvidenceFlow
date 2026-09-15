from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol


class CrmError(Exception):
    code = "crm_error"


class CrmUnavailable(CrmError):
    code = "crm_unavailable"


class CrmRejected(CrmError):
    code = "crm_rejected"


@dataclass(frozen=True)
class CrmRecord:
    external_id: str
    created: bool


class CrmClient(Protocol):
    def create_record(self, idempotency_key: str, payload: dict[str, Any]) -> CrmRecord: ...


class DatabaseCrm:
    """A mock destination whose deduplication is shared by every process.

    An in-memory mock only proves the contract inside one process; the API and the
    worker are separate processes in a real deployment.
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def create_record(self, idempotency_key: str, payload: dict[str, Any]) -> CrmRecord:
        from sqlalchemy.exc import IntegrityError

        from app.repositories.models import CrmRecordRow
        from app.repositories.session import session_scope

        external_id = external_id_for(idempotency_key)
        try:
            with session_scope(self._session_factory) as session:
                session.add(
                    CrmRecordRow(
                        idempotency_key=idempotency_key,
                        external_id=external_id,
                        payload=payload,
                    )
                )
        except IntegrityError:
            return CrmRecord(external_id=external_id, created=False)
        return CrmRecord(external_id=external_id, created=True)


def external_id_for(idempotency_key: str) -> str:
    return f"CRM-{idempotency_key[:10].upper()}"


@dataclass
class MockCrm:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    failures: list[CrmError] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def create_record(self, idempotency_key: str, payload: dict[str, Any]) -> CrmRecord:
        with self._lock:
            self.calls.append(idempotency_key)
            if self.failures:
                raise self.failures.pop(0)
            stored = self.records.get(idempotency_key)
            if stored is not None:
                return CrmRecord(external_id=stored["external_id"], created=False)
            external_id = f"CRM-{len(self.records) + 1:05d}"
            self.records[idempotency_key] = {"external_id": external_id, "payload": payload}
            return CrmRecord(external_id=external_id, created=True)
