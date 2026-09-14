from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.domain.jobs import DEFAULT_LEASE, JobType
from app.providers.base import ExtractionProvider
from app.providers.crm import CrmClient
from app.repositories import documents as repo
from app.repositories.models import Job
from app.repositories.session import session_scope
from app.services.crm_write import write_approved_record
from app.services.extraction import extract_document
from app.services.validation import validate_extraction
from app.workflows import queue

IDLE_SLEEP_SECONDS = 0.5


@dataclass
class Worker:
    session_factory: sessionmaker[Session]
    provider: ExtractionProvider
    crm: CrmClient
    worker_id: str = "worker-1"
    lease: timedelta = DEFAULT_LEASE
    processed: list[str] = field(default_factory=list)

    def run_once(self) -> Job | None:
        job_id = self._claim()
        if job_id is None:
            return None

        with session_scope(self.session_factory) as session:
            error = self._dispatch(session, session.get(Job, job_id))

        with session_scope(self.session_factory) as session:
            job = session.get(Job, job_id)
            queue.fail(session, job, error) if error else queue.succeed(session, job)
            self.processed.append(job_id)
            return job

    def _claim(self) -> str | None:
        with session_scope(self.session_factory) as session:
            queue.reclaim_expired(session)
            job = queue.claim(session, worker_id=self.worker_id, lease=self.lease)
            return job.id if job else None

    def run_forever(self, stop: threading.Event, idle_sleep: float = IDLE_SLEEP_SECONDS) -> None:
        while not stop.is_set():
            if self.run_once() is None:
                stop.wait(idle_sleep)

    def drain(self, limit: int = 100) -> int:
        completed = 0
        while completed < limit and self.run_once() is not None:
            completed += 1
        return completed

    def _dispatch(self, session: Session, job: Job) -> Exception | None:
        """Returns the failure instead of raising, so recorded audit rows still commit."""
        document = repo.get_document(session, job.document_id)
        if document is None:
            return LookupError(f"document {job.document_id} no longer exists")
        try:
            if job.type == JobType.EXTRACT:
                outcome = extract_document(session, document, self.provider)
                if outcome.error is not None:
                    return outcome.error
                validate_extraction(session, document, outcome.extraction)
            elif job.type == JobType.WRITE:
                write_approved_record(session, document, self.crm)
            else:
                return LookupError(f"unknown job type {job.type}")
        except Exception as exc:
            return exc
        return None


def run_in_background(worker: Worker) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(target=worker.run_forever, args=(stop,), daemon=True)
    thread.start()
    return thread, stop


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
