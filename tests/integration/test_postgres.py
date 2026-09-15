from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import text

from app.domain.approval import idempotency_key
from app.domain.events import DocumentStatus
from app.domain.jobs import JobType
from app.migrate import upgrade_to_head
from app.providers.crm import DatabaseCrm
from app.providers.fake import FakeProvider
from app.repositories import documents as repo
from app.repositories.models import Base, CrmRecordRow, CrmWrite, Job
from app.repositories.session import build_engine, build_session_factory, session_scope
from app.services.approval import approve_extraction
from app.services.crm_write import write_approved_record
from app.services.extraction import extract_document
from app.services.validation import validate_extraction
from app.workflows import queue
from app.workflows.worker import Worker
from tests.integration.test_migrations import _shape

POSTGRES_URL = os.getenv("EVIDENCEFLOW_TEST_POSTGRES_URL", "")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="set EVIDENCEFLOW_TEST_POSTGRES_URL to run PostgreSQL tests"
)

ACTOR = "reviewer@example.com"
NAME = "inv_001_acme"
WORKERS = 6


@pytest.fixture
def postgres(settings):
    engine = build_engine(POSTGRES_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    upgrade_to_head(POSTGRES_URL)
    return build_session_factory(
        replace(settings, database_url=POSTGRES_URL, auto_create_schema=False)
    )


def test_migrations_match_the_models_on_postgres(postgres):
    shape = _shape(build_engine(POSTGRES_URL))

    assert set(shape) == set(Base.metadata.tables)
    assert shape["crm_write"]["unique"] == [("idempotency_key",)]


def _seed(factory, fixtures, name=NAME) -> str:
    with session_scope(factory) as session:
        return repo.create_document(
            session, filename=name, source_text=fixtures.text(name)
        ).id


def test_concurrent_workers_claim_each_job_once(postgres, fixtures):
    documents = [_seed(postgres, fixtures, name) for name in ("inv_001_acme", "inv_002_northwind")]
    with session_scope(postgres) as session:
        for document_id in documents:
            queue.enqueue(session, type=JobType.EXTRACT, document_id=document_id)

    workers = [
        Worker(
            session_factory=postgres,
            provider=FakeProvider.from_fixtures(fixtures.directory),
            crm=DatabaseCrm(postgres),
            worker_id=f"worker-{index}",
        )
        for index in range(WORKERS)
    ]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        claimed = [job for job in pool.map(lambda worker: worker.run_once(), workers) if job]

    assert len({job.id for job in claimed}) == len(claimed) == 2
    with session_scope(postgres) as session:
        assert session.query(Job).count() == 2
        assert all(job.attempts == 1 for job in session.query(Job).all())


def test_concurrent_writes_create_one_record_on_postgres(postgres, fixtures):
    document_id = _seed(postgres, fixtures)
    with session_scope(postgres) as session:
        document = repo.get_document(session, document_id)
        extraction = extract_document(
            session, document, FakeProvider.from_fixtures(fixtures.directory)
        ).extraction
        validate_extraction(session, document, extraction)
        approve_extraction(session, document, extraction, actor=ACTOR)
        payload_hash = extraction.payload_hash

    crm = DatabaseCrm(postgres)

    def attempt(_):
        try:
            with session_scope(postgres) as session:
                outcome = write_approved_record(
                    session, repo.get_document(session, document_id), crm
                )
                return "called" if outcome.called_destination else "no-op"
        except Exception as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(attempt, range(WORKERS)))

    key = idempotency_key(document_id, payload_hash)
    with session_scope(postgres) as session:
        assert session.query(CrmWrite).filter_by(idempotency_key=key).count() == 1
        assert session.query(CrmRecordRow).count() == 1
        assert repo.get_document(session, document_id).status == DocumentStatus.WRITTEN
    assert results.count("called") == 1
