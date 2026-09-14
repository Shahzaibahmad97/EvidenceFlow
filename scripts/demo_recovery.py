"""Interrupt the worker mid-write, restart it, and show one destination record.

    python scripts/demo_recovery.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.app import build_provider  # noqa: E402
from app.config import Settings  # noqa: E402
from app.domain.approval import now  # noqa: E402
from app.domain.jobs import JobType  # noqa: E402
from app.providers.crm import CrmUnavailable, MockCrm  # noqa: E402
from app.repositories import documents as repo  # noqa: E402
from app.repositories.models import Job  # noqa: E402
from app.repositories.session import build_session_factory, session_scope  # noqa: E402
from app.services.approval import approve_extraction  # noqa: E402
from app.workflows import queue  # noqa: E402
from app.workflows.worker import Worker  # noqa: E402

DOCUMENTS = ROOT / "tests" / "fixtures" / "invoices"
NAME = "inv_004_meridian"
ACTOR = "reviewer@example.com"


def main() -> int:
    with TemporaryDirectory() as directory:
        return _run(f"sqlite:///{Path(directory) / 'recovery.db'}")


def _run(database_url: str) -> int:
    settings = replace(Settings.from_env(), database_url=database_url, provider="fake")
    provider = build_provider(settings)
    crm = MockCrm()
    factory = build_session_factory(settings)
    worker = Worker(session_factory=factory, provider=provider, crm=crm, worker_id="worker-a")

    with session_scope(factory) as session:
        document = repo.create_document(
            session, filename=NAME, source_text=(DOCUMENTS / f"{NAME}.txt").read_text()
        )
        document_id = document.id
        queue.enqueue(session, type=JobType.EXTRACT, document_id=document_id)

    crm.failures.append(CrmUnavailable("503 from destination"))
    worker.run_once()
    print("1. extract job succeeded, document validated")

    with session_scope(factory) as session:
        document = repo.get_document(session, document_id)
        extraction = repo.latest_extraction(session, document_id)
        approve_extraction(session, document, extraction, actor=ACTOR)
        write_job_id = queue.enqueue(session, type=JobType.WRITE, document_id=document_id).id

    worker.run_once()
    with session_scope(factory) as session:
        job = session.get(Job, write_job_id)
        print(f"2. destination returned 503 -> job {job.status}, attempt {job.attempts}")
        print(f"   retry scheduled, classified transient: {job.last_error}")
        job.run_at = now()

    with session_scope(factory) as session:
        claimed = queue.claim(session, worker_id="worker-that-dies")
        claimed.lease_expires_at = now() - timedelta(seconds=1)
        print(f"3. worker claimed job (attempt {claimed.attempts}) then died mid-write")

    restarted = build_session_factory(replace(settings, database_url=database_url))
    recovered = Worker(
        session_factory=restarted, provider=provider, crm=crm, worker_id="worker-b"
    ).run_once()
    print(f"4. new worker reclaimed the expired lease -> {recovered.status}, attempt {recovered.attempts}")

    with session_scope(restarted) as session:
        document = repo.get_document(session, document_id)
        events = [event.type for event in repo.list_events(session, document_id)]
    print(f"5. document status {document.status}, destination records {len(crm.records)}")
    print(f"   destination calls {len(crm.calls)}")
    print(f"6. audit trail survived: {' -> '.join(events)}")
    return 0 if len(crm.records) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
