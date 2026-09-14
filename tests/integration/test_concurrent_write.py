from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.domain.approval import idempotency_key
from app.domain.events import DocumentStatus, EventType
from app.providers.crm import MockCrm
from app.repositories import documents as repo
from app.repositories.models import CrmWrite, Event
from app.repositories.session import session_scope
from app.services.approval import approve_extraction
from app.services.crm_write import write_approved_record
from app.services.extraction import extract_document
from app.services.validation import validate_extraction

ACTOR = "reviewer@example.com"
NAME = "inv_003_bluepeak"
WRITERS = 8


def _prepare(factory, fixtures) -> tuple[str, str]:
    with session_scope(factory) as session:
        document = repo.create_document(
            session, filename=f"{NAME}.txt", source_text=fixtures.text(NAME)
        )
        extraction = extract_document(session, document, fixtures.provider(NAME)).extraction
        validate_extraction(session, document, extraction)
        approve_extraction(session, document, extraction, actor=ACTOR)
        return document.id, extraction.payload_hash


def _attempt(factory, document_id: str, crm: MockCrm) -> str:
    try:
        with session_scope(factory) as session:
            document = repo.get_document(session, document_id)
            outcome = write_approved_record(session, document, crm)
            return "called" if outcome.called_destination else "no-op"
    except Exception as exc:
        return type(exc).__name__


def test_concurrent_writers_create_one_record(file_session_factory, fixtures):
    crm = MockCrm()
    document_id, payload_hash = _prepare(file_session_factory, fixtures)

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(
            pool.map(lambda _: _attempt(file_session_factory, document_id, crm), range(WRITERS))
        )

    assert len(crm.records) == 1
    assert results.count("called") == 1

    with session_scope(file_session_factory) as session:
        key = idempotency_key(document_id, payload_hash)
        rows = session.scalars(select(CrmWrite).where(CrmWrite.idempotency_key == key)).all()
        document = repo.get_document(session, document_id)
        succeeded = session.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.document_id == document_id, Event.type == EventType.WRITE_SUCCEEDED)
        )

    assert len(rows) == 1
    assert document.status == DocumentStatus.WRITTEN
    assert succeeded == 1


def test_a_replay_storm_after_the_write_calls_the_destination_once(file_session_factory, fixtures):
    crm = MockCrm()
    document_id, _ = _prepare(file_session_factory, fixtures)
    _attempt(file_session_factory, document_id, crm)

    with ThreadPoolExecutor(max_workers=WRITERS) as pool:
        results = list(
            pool.map(lambda _: _attempt(file_session_factory, document_id, crm), range(20))
        )

    assert set(results) == {"no-op"}
    assert len(crm.calls) == 1
