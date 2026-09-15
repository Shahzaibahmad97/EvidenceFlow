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
    """A mock destination that stores its records where every process can see them.

    It writes inside the caller's transaction, through a savepoint, because a second
    connection would deadlock against the caller's write lock on SQLite. Its unique
    constraints are the guarantee, not the connection it holds them on.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    def create_record(self, idempotency_key: str, payload: dict[str, Any]) -> CrmRecord:
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        from app.repositories.documents import business_key
        from app.repositories.models import CrmRecordRow

        key = business_key(payload)
        if key is None:
            raise CrmRejected("record carries no supplier and invoice number")

        external_id = external_id_for(idempotency_key)
        try:
            with self._session.begin_nested():
                self._session.add(
                    CrmRecordRow(
                        idempotency_key=idempotency_key,
                        business_key=":".join(key),
                        external_id=external_id,
                        payload=payload,
                    )
                )
        except IntegrityError:
            existing = self._session.scalars(
                select(CrmRecordRow).where(CrmRecordRow.idempotency_key == idempotency_key)
            ).first()
            if existing is not None:
                return CrmRecord(external_id=existing.external_id, created=False)
            raise CrmRejected(f"invoice {key[1]} is already recorded for this supplier") from None
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
