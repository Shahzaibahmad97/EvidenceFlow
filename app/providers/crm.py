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
