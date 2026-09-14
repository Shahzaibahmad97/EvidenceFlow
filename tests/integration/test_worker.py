from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.approval import as_utc, now
from app.domain.events import DocumentStatus, WriteStatus
from app.domain.jobs import FailureKind, JobStatus, JobType
from app.providers.base import ProviderTimeout
from app.providers.crm import CrmRejected, CrmUnavailable, MockCrm
from app.providers.fake import FakeProvider
from app.repositories import documents as repo
from app.repositories.models import Job
from app.repositories.session import session_scope
from app.services.approval import approve_extraction
from app.services.crm_write import write_approved_record
from app.services.extraction import extract_document
from app.services.validation import validate_extraction
from app.workflows import queue
from app.workflows.worker import Worker

NAME = "inv_001_acme"
ACTOR = "reviewer@example.com"


@pytest.fixture
def crm() -> MockCrm:
    return MockCrm()


def build_worker(factory, fixtures, crm, provider=None, worker_id="worker-1", **kwargs) -> Worker:
    return Worker(
        session_factory=factory,
        provider=provider or FakeProvider.from_fixtures(fixtures.directory),
        crm=crm,
        worker_id=worker_id,
        **kwargs,
    )


def seed_document(factory, fixtures, name=NAME) -> str:
    with session_scope(factory) as session:
        document = repo.create_document(
            session, filename=name, source_text=fixtures.text(name)
        )
        return document.id


def enqueue(factory, document_id, job_type) -> str:
    with session_scope(factory) as session:
        return queue.enqueue(session, type=job_type, document_id=document_id).id


def read_job(factory, job_id) -> Job:
    with session_scope(factory) as session:
        return session.get(Job, job_id)


def test_an_extract_job_runs_the_whole_intake(file_session_factory, fixtures, crm):
    document_id = seed_document(file_session_factory, fixtures)
    job_id = enqueue(file_session_factory, document_id, JobType.EXTRACT)

    build_worker(file_session_factory, fixtures, crm).run_once()

    job = read_job(file_session_factory, job_id)
    with session_scope(file_session_factory) as session:
        document = repo.get_document(session, document_id)
        assert document.status == DocumentStatus.VALIDATED
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempts == 1


def test_an_idle_queue_returns_nothing(file_session_factory, fixtures, crm):
    assert build_worker(file_session_factory, fixtures, crm).run_once() is None


def test_a_timeout_is_retried_with_backoff(file_session_factory, fixtures, crm):
    document_id = seed_document(file_session_factory, fixtures)
    job_id = enqueue(file_session_factory, document_id, JobType.EXTRACT)
    worker = build_worker(
        file_session_factory,
        fixtures,
        crm,
        provider=FakeProvider.raising(ProviderTimeout("read timeout")),
    )

    worker.run_once()

    job = read_job(file_session_factory, job_id)
    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert as_utc(job.run_at) > now()
    assert "provider_timeout" in job.last_error


def test_retries_are_exhausted_then_the_job_goes_to_review(file_session_factory, fixtures, crm):
    document_id = seed_document(file_session_factory, fixtures)
    with session_scope(file_session_factory) as session:
        job_id = queue.enqueue(
            session, type=JobType.EXTRACT, document_id=document_id, max_attempts=2
        ).id
    worker = build_worker(
        file_session_factory,
        fixtures,
        crm,
        provider=FakeProvider.raising(ProviderTimeout("read timeout")),
    )

    for _ in range(2):
        with session_scope(file_session_factory) as session:
            session.get(Job, job_id).run_at = now()
        worker.run_once()

    job = read_job(file_session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert job.failure_kind == FailureKind.TRANSIENT_EXHAUSTED
    assert job.attempts == 2


def test_a_permanent_failure_is_not_retried(file_session_factory, fixtures, crm):
    document_id = seed_document(file_session_factory, fixtures, "fail_bad_currency")
    job_id = enqueue(file_session_factory, document_id, JobType.EXTRACT)

    build_worker(file_session_factory, fixtures, crm).run_once()

    job = read_job(file_session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert job.failure_kind == FailureKind.PERMANENT
    assert job.attempts == 1
    assert "malformed_provider_output" in job.last_error


def test_the_review_queue_lists_failed_jobs(file_session_factory, fixtures, crm):
    document_id = seed_document(file_session_factory, fixtures, "fail_missing_invoice_number")
    enqueue(file_session_factory, document_id, JobType.EXTRACT)
    build_worker(file_session_factory, fixtures, crm).run_once()

    with session_scope(file_session_factory) as session:
        failed = queue.review_queue(session)

    assert [job.document_id for job in failed] == [document_id]


def test_only_one_worker_claims_a_job(file_session_factory, fixtures, crm):
    document_id = seed_document(file_session_factory, fixtures)
    enqueue(file_session_factory, document_id, JobType.EXTRACT)
    first = build_worker(file_session_factory, fixtures, crm, worker_id="worker-a")
    second = build_worker(file_session_factory, fixtures, crm, worker_id="worker-b")

    claimed = [first.run_once(), second.run_once()]

    assert sum(job is not None for job in claimed) == 1


def approve_and_enqueue_write(factory, fixtures, crm) -> tuple[str, str]:
    document_id = seed_document(factory, fixtures)
    with session_scope(factory) as session:
        document = repo.get_document(session, document_id)
        extraction = extract_document(
            session, document, FakeProvider.from_fixtures(fixtures.directory)
        ).extraction
        validate_extraction(session, document, extraction)
        approve_extraction(session, document, extraction, actor=ACTOR)
        job_id = queue.enqueue(session, type=JobType.WRITE, document_id=document_id).id
    return document_id, job_id


def test_a_write_job_writes_once(file_session_factory, fixtures, crm):
    document_id, job_id = approve_and_enqueue_write(file_session_factory, fixtures, crm)

    build_worker(file_session_factory, fixtures, crm).run_once()

    assert read_job(file_session_factory, job_id).status == JobStatus.SUCCEEDED
    assert len(crm.records) == 1
    with session_scope(file_session_factory) as session:
        assert repo.get_document(session, document_id).status == DocumentStatus.WRITTEN


def test_a_duplicate_write_job_creates_no_second_record(file_session_factory, fixtures, crm):
    document_id, _ = approve_and_enqueue_write(file_session_factory, fixtures, crm)
    enqueue(file_session_factory, document_id, JobType.WRITE)

    worker = build_worker(file_session_factory, fixtures, crm)
    worker.drain()

    assert len(crm.records) == 1
    assert len(crm.calls) == 1


def test_a_destination_outage_retries_and_still_writes_once(file_session_factory, fixtures, crm):
    document_id, job_id = approve_and_enqueue_write(file_session_factory, fixtures, crm)
    crm.failures.append(CrmUnavailable("503 from destination"))
    worker = build_worker(file_session_factory, fixtures, crm)

    worker.run_once()
    assert read_job(file_session_factory, job_id).status == JobStatus.PENDING

    with session_scope(file_session_factory) as session:
        session.get(Job, job_id).run_at = now()
    worker.run_once()

    job = read_job(file_session_factory, job_id)
    assert job.status == JobStatus.SUCCEEDED
    assert job.attempts == 2
    assert len(crm.records) == 1


def test_a_rejected_write_goes_to_review_without_retry(file_session_factory, fixtures, crm):
    _, job_id = approve_and_enqueue_write(file_session_factory, fixtures, crm)
    crm.failures.append(CrmRejected("422 unprocessable"))

    build_worker(file_session_factory, fixtures, crm).run_once()

    job = read_job(file_session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert job.failure_kind == FailureKind.PERMANENT


def test_an_interrupted_write_is_reclaimed_and_completes_once(file_session_factory, fixtures, crm):
    document_id, job_id = approve_and_enqueue_write(file_session_factory, fixtures, crm)

    with session_scope(file_session_factory) as session:
        claimed = queue.claim(session, worker_id="worker-that-dies", lease=timedelta(seconds=30))
        assert claimed.id == job_id
        claimed.lease_expires_at = now() - timedelta(seconds=1)

    recovered = build_worker(file_session_factory, fixtures, crm, worker_id="worker-b").run_once()

    assert recovered.id == job_id
    assert recovered.status == JobStatus.SUCCEEDED
    assert recovered.attempts == 2
    assert len(crm.records) == 1
    with session_scope(file_session_factory) as session:
        assert repo.get_document(session, document_id).status == DocumentStatus.WRITTEN


def test_a_live_lease_is_not_stolen(file_session_factory, fixtures, crm):
    _, job_id = approve_and_enqueue_write(file_session_factory, fixtures, crm)
    with session_scope(file_session_factory) as session:
        queue.claim(session, worker_id="worker-a", lease=timedelta(minutes=5))

    assert build_worker(file_session_factory, fixtures, crm, worker_id="worker-b").run_once() is None
    assert crm.calls == []


def test_work_survives_a_process_restart(file_session_factory, fixtures, crm, settings):
    from dataclasses import replace

    from app.repositories.session import build_session_factory

    document_id, job_id = approve_and_enqueue_write(file_session_factory, fixtures, crm)
    url = str(file_session_factory.kw["bind"].url)

    restarted = build_session_factory(replace(settings, database_url=url))
    build_worker(restarted, fixtures, crm, worker_id="worker-after-restart").run_once()

    with session_scope(restarted) as session:
        assert session.get(Job, job_id).status == JobStatus.SUCCEEDED
        assert repo.get_document(session, document_id).status == DocumentStatus.WRITTEN
    assert len(crm.records) == 1


def test_an_interrupted_write_that_reached_the_destination_is_not_repeated(
    file_session_factory, fixtures, crm
):
    document_id, job_id = approve_and_enqueue_write(file_session_factory, fixtures, crm)
    with session_scope(file_session_factory) as session:
        document = repo.get_document(session, document_id)
        write_approved_record(session, document, crm)
        claimed = queue.claim(session, worker_id="worker-that-dies")
        claimed.lease_expires_at = now() - timedelta(seconds=1)

    build_worker(file_session_factory, fixtures, crm, worker_id="worker-b").run_once()

    with session_scope(file_session_factory) as session:
        write = repo.find_write(session, _key(session, document_id))
        assert write.status == WriteStatus.SUCCEEDED
    assert len(crm.calls) == 1
    assert read_job(file_session_factory, job_id).status == JobStatus.SUCCEEDED


def _key(session, document_id: str) -> str:
    from app.domain.approval import idempotency_key

    document = repo.get_document(session, document_id)
    return idempotency_key(document_id, document.approved_payload_hash)
