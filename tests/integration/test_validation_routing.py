from __future__ import annotations

import pytest

from app.domain.events import DocumentStatus, EventType
from app.repositories import documents as repo
from app.services.extraction import extract_document
from app.services.validation import validate_extraction


def _intake(session, fixtures, name):
    document = repo.create_document(
        session, filename=f"{name}.txt", source_text=fixtures.text(name)
    )
    outcome = extract_document(session, document, fixtures.provider(name))
    results = validate_extraction(session, document, outcome.extraction)
    return document, outcome.extraction, results


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("inv_001_acme", DocumentStatus.VALIDATED),
        ("adv_line_discount", DocumentStatus.VALIDATED),
        ("adv_credit_note", DocumentStatus.VALIDATED),
        ("adv_rounding_drift", DocumentStatus.NEEDS_REVIEW),
        ("adv_ambiguous_date", DocumentStatus.NEEDS_REVIEW),
        ("adv_document_discount", DocumentStatus.NEEDS_REVIEW),
        ("adv_unsupported_currency", DocumentStatus.NEEDS_REVIEW),
    ],
)
def test_routing_matches_the_rules(session, fixtures, name, status):
    document, _, _ = _intake(session, fixtures, name)

    assert document.status == status


def test_validation_results_are_stored_apart_from_the_extraction(session, fixtures):
    _, extraction, results = _intake(session, fixtures, "adv_totals_dont_add")
    stored = repo.list_validation_results(session, extraction.id)

    assert len(stored) == len(results) == 11
    assert "subtotal_plus_tax_equals_total" in {
        row.rule for row in stored if row.outcome == "fail"
    }
    assert "validation" not in (extraction.draft or {})


def test_validation_completed_event_names_the_blocking_rules(session, fixtures):
    document, _, _ = _intake(session, fixtures, "adv_credit_note_mis_signed")
    event = next(
        e
        for e in repo.list_events(session, document.id)
        if e.type == EventType.VALIDATION_COMPLETED
    )

    assert event.payload["accepted"] is False
    assert "credit_note_consistent" in {item["rule"] for item in event.payload["blocking"]}


def test_a_redelivered_invoice_number_is_blocked_once_the_first_is_committed(session, fixtures):
    from app.providers.crm import MockCrm
    from app.services.approval import approve_extraction
    from app.services.crm_write import write_approved_record

    first, extraction, _ = _intake(session, fixtures, "inv_001_acme")
    approve_extraction(session, first, extraction, actor="reviewer@example.com")
    write_approved_record(session, first, MockCrm())

    document, _, results = _intake(session, fixtures, "adv_duplicate_number")

    assert document.status == DocumentStatus.NEEDS_REVIEW
    assert "invoice_number_not_duplicate" in [r.rule for r in results if r.blocking]


def test_an_uncommitted_document_does_not_claim_its_invoice_number(session, fixtures):
    _intake(session, fixtures, "inv_001_acme")

    document, _, results = _intake(session, fixtures, "adv_duplicate_number")

    assert document.status == DocumentStatus.VALIDATED
    assert [r.rule for r in results if r.blocking] == []


def test_a_document_is_not_a_duplicate_of_itself(session, fixtures):
    document, extraction, _ = _intake(session, fixtures, "inv_002_northwind")

    results = validate_extraction(session, document, extraction)

    assert document.status == DocumentStatus.VALIDATED
    assert not [r for r in results if r.rule == "invoice_number_not_duplicate" and r.blocking]
