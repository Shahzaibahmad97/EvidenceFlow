from __future__ import annotations

import pytest

from app.domain.events import DocumentStatus, EventType, ExtractionStatus
from app.providers.base import (
    MalformedProviderOutput,
    ProviderRefusal,
    ProviderTimeout,
)
from app.providers.fake import FakeProvider
from app.repositories import documents as repo
from app.services.extraction import extract_document


def _document(session, fixtures, name):
    return repo.create_document(session, filename=f"{name}.txt", source_text=fixtures.text(name))


def _event_types(session, document_id):
    return [event.type for event in repo.list_events(session, document_id)]


def test_happy_path_records_draft_evidence_and_events(session, fixtures):
    name = "inv_001_acme"
    document = _document(session, fixtures, name)

    outcome = extract_document(session, document, fixtures.provider(name, latency_ms=42))

    assert outcome.succeeded
    assert document.status == DocumentStatus.EXTRACTED
    assert outcome.extraction.payload_hash
    assert outcome.extraction.latency_ms == 42
    assert all(item["verified"] for item in outcome.extraction.evidence)
    assert _event_types(session, document.id) == [
        EventType.EXTRACTION_REQUESTED,
        EventType.EVIDENCE_VERIFIED,
        EventType.EXTRACTION_SUCCEEDED,
    ]


def test_every_accepted_field_carries_a_resolved_span(session, fixtures):
    name = "inv_004_meridian"
    document = _document(session, fixtures, name)

    outcome = extract_document(session, document, fixtures.provider(name))

    source = document.source_text
    for item in outcome.extraction.evidence:
        assert source[item["start"] : item["end"]].split() == item["quote"].split()


def test_unverifiable_evidence_routes_to_review(session, fixtures):
    name = "fail_unverifiable_quote"
    document = _document(session, fixtures, name)

    outcome = extract_document(session, document, fixtures.provider(name))

    assert outcome.succeeded
    assert document.status == DocumentStatus.NEEDS_REVIEW
    assert EventType.EVIDENCE_REJECTED in _event_types(session, document.id)
    rejected = [item for item in outcome.extraction.evidence if not item["verified"]]
    assert [item["field"] for item in rejected] == ["subtotal"]
    assert rejected[0]["start"] is None


@pytest.mark.parametrize("name", ["fail_missing_invoice_number", "fail_bad_currency"])
def test_schema_invalid_output_fails_the_extraction(session, fixtures, name):
    document = _document(session, fixtures, name)

    outcome = extract_document(session, document, fixtures.provider(name))

    assert not outcome.succeeded
    assert outcome.extraction.error_code == MalformedProviderOutput.code
    assert outcome.extraction.draft is None
    assert document.status == DocumentStatus.EXTRACTION_FAILED


def test_malformed_output_is_recorded_with_provider_metadata(session, fixtures):
    document = _document(session, fixtures, "inv_001_acme")

    outcome = extract_document(session, document, FakeProvider.returning({"nonsense": True}))

    assert outcome.extraction.status == ExtractionStatus.FAILED
    assert outcome.extraction.raw_payload == {"nonsense": True}
    assert outcome.extraction.model == "fake-extractor-1"


@pytest.mark.parametrize(
    "error", [ProviderTimeout("timed out"), ProviderRefusal("refused to answer")]
)
def test_provider_failures_still_create_an_extraction_attempt(session, fixtures, error):
    document = _document(session, fixtures, "inv_002_northwind")

    outcome = extract_document(session, document, FakeProvider.raising(error))

    assert outcome.extraction.id
    assert outcome.extraction.error_code == error.code
    assert _event_types(session, document.id) == [
        EventType.EXTRACTION_REQUESTED,
        EventType.EXTRACTION_FAILED,
    ]


def test_model_output_is_never_promoted_to_the_document(session, fixtures):
    name = "inv_005_calder"
    document = _document(session, fixtures, name)

    extract_document(session, document, fixtures.provider(name))

    assert not hasattr(document, "total")
    assert document.source_text == fixtures.text(name)


def test_repeated_extraction_appends_rather_than_overwrites(session, fixtures):
    name = "inv_003_bluepeak"
    document = _document(session, fixtures, name)

    first = extract_document(session, document, fixtures.provider(name))
    second = extract_document(session, document, fixtures.provider(name))

    assert first.extraction.id != second.extraction.id
    assert first.extraction.payload_hash == second.extraction.payload_hash
    assert len(repo.list_events(session, document.id)) == 6
    assert repo.latest_extraction(session, document.id).id == second.extraction.id


def test_fixture_provider_serves_every_committed_invoice(session, fixtures):
    provider = FakeProvider.from_fixtures(fixtures.directory)

    for name in ["inv_001_acme", "inv_002_northwind", "inv_005_calder"]:
        document = _document(session, fixtures, name)
        assert extract_document(session, document, provider).succeeded
