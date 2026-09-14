from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.approval import (
    AlreadyWritten,
    ApprovalExpired,
    ApprovalMissing,
    ExtractionSupersededError,
    NotReadyForApproval,
    idempotency_key,
)
from app.domain.events import DocumentStatus, EventType, WriteStatus
from app.providers.crm import CrmUnavailable, MockCrm
from app.repositories import documents as repo
from app.services.approval import approve_extraction
from app.services.crm_write import write_approved_record
from app.services.extraction import extract_document
from app.services.validation import validate_extraction

ACTOR = "reviewer@example.com"


def intake(session, fixtures, name="inv_001_acme"):
    document = repo.create_document(
        session, filename=f"{name}.txt", source_text=fixtures.text(name)
    )
    extraction = extract_document(session, document, fixtures.provider(name)).extraction
    validate_extraction(session, document, extraction)
    return document, extraction


@pytest.fixture
def crm() -> MockCrm:
    return MockCrm()


def test_approval_binds_to_the_payload_hash(session, fixtures):
    document, extraction = intake(session, fixtures)

    approval = approve_extraction(session, document, extraction, actor=ACTOR)

    assert approval.payload_hash == extraction.payload_hash
    assert approval.actor == ACTOR
    assert document.status == DocumentStatus.APPROVED
    assert document.approved_payload_hash == extraction.payload_hash


def test_a_document_in_review_cannot_be_approved(session, fixtures):
    document, extraction = intake(session, fixtures, "adv_rounding_drift")

    with pytest.raises(NotReadyForApproval):
        approve_extraction(session, document, extraction, actor=ACTOR)

    assert document.approved_payload_hash is None


def test_approving_a_superseded_extraction_is_refused(session, fixtures):
    document, first = intake(session, fixtures)
    replacement = extract_document(
        session, document, fixtures.provider("inv_001_acme")
    ).extraction
    validate_extraction(session, document, replacement)

    with pytest.raises(ExtractionSupersededError):
        approve_extraction(session, document, first, actor=ACTOR)

    assert approve_extraction(session, document, replacement, actor=ACTOR).extraction_id == (
        replacement.id
    )


def test_write_without_approval_is_refused(session, fixtures, crm):
    document, _ = intake(session, fixtures)

    with pytest.raises(ApprovalMissing):
        write_approved_record(session, document, crm)

    assert crm.calls == []


def test_approved_write_creates_exactly_one_record(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)

    outcome = write_approved_record(session, document, crm)

    assert outcome.called_destination
    assert outcome.external_id == "CRM-00001"
    assert document.status == DocumentStatus.WRITTEN
    assert len(crm.records) == 1


def test_twenty_replays_create_one_record(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)

    outcomes = [write_approved_record(session, document, crm) for _ in range(20)]

    assert sum(outcome.called_destination for outcome in outcomes) == 1
    assert len(crm.calls) == 1
    assert len(crm.records) == 1
    assert {outcome.external_id for outcome in outcomes} == {"CRM-00001"}


def test_the_idempotency_key_is_derived_from_document_and_payload(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)

    outcome = write_approved_record(session, document, crm)

    assert outcome.write.idempotency_key == idempotency_key(
        document.id, extraction.payload_hash
    )


def test_a_correction_after_approval_blocks_the_write(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)
    extract_document(session, document, fixtures.provider("inv_001_acme"))

    with pytest.raises(ApprovalMissing):
        write_approved_record(session, document, crm)

    assert crm.calls == []
    assert document.approved_payload_hash is None


def test_an_expired_approval_blocks_the_write(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR, ttl=timedelta(seconds=-1))

    with pytest.raises(ApprovalExpired):
        write_approved_record(session, document, crm)

    assert crm.calls == []


def test_a_replay_after_expiry_is_still_a_no_op_not_an_error(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approval = approve_extraction(session, document, extraction, actor=ACTOR)
    write_approved_record(session, document, crm)

    approval.expires_at = approval.created_at - timedelta(minutes=1)
    session.flush()
    outcome = write_approved_record(session, document, crm)

    assert not outcome.called_destination
    assert len(crm.calls) == 1


def test_a_second_approval_of_the_same_payload_writes_once(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)
    write_approved_record(session, document, crm)
    document.status = DocumentStatus.VALIDATED

    approve_extraction(session, document, extraction, actor=ACTOR)
    with pytest.raises(AlreadyWritten):
        write_approved_record(session, document, crm)

    assert len(crm.records) == 1


def test_a_destination_outage_leaves_the_write_retryable(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)
    crm.failures.append(CrmUnavailable("503 from destination"))

    with pytest.raises(CrmUnavailable):
        write_approved_record(session, document, crm)

    assert repo.find_write(session, idempotency_key(document.id, extraction.payload_hash)).status == (
        WriteStatus.FAILED
    )
    assert document.status == DocumentStatus.APPROVED

    outcome = write_approved_record(session, document, crm)

    assert outcome.called_destination
    assert outcome.write.attempts == 2
    assert len(crm.records) == 1


def test_the_document_transition_is_guarded(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)
    document.approved_payload_hash = "a-different-hash"

    with pytest.raises(ApprovalMissing):
        write_approved_record(session, document, crm)


def test_the_event_trail_records_the_whole_slice(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)
    write_approved_record(session, document, crm)

    assert [event.type for event in repo.list_events(session, document.id)] == [
        EventType.EXTRACTION_REQUESTED,
        EventType.EVIDENCE_VERIFIED,
        EventType.EXTRACTION_SUCCEEDED,
        EventType.VALIDATION_COMPLETED,
        EventType.APPROVAL_GRANTED,
        EventType.WRITE_ATTEMPTED,
        EventType.WRITE_SUCCEEDED,
    ]


def test_the_approving_actor_is_recorded(session, fixtures, crm):
    document, extraction = intake(session, fixtures)
    approve_extraction(session, document, extraction, actor=ACTOR)

    granted = next(
        event
        for event in repo.list_events(session, document.id)
        if event.type == EventType.APPROVAL_GRANTED
    )

    assert granted.actor == ACTOR
