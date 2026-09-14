from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.approval import DEFAULT_APPROVAL_TTL, as_utc, expiry_from, idempotency_key

HASH = "a" * 64


def test_the_key_is_stable_for_the_same_document_and_payload():
    assert idempotency_key("doc-1", HASH) == idempotency_key("doc-1", HASH)


def test_identical_content_in_different_documents_gets_different_keys():
    assert idempotency_key("doc-1", HASH) != idempotency_key("doc-2", HASH)


def test_a_changed_payload_gets_a_different_key():
    assert idempotency_key("doc-1", HASH) != idempotency_key("doc-1", "b" * 64)


def test_the_key_cannot_be_confused_by_boundary_shifting():
    assert idempotency_key("doc", "1:x") != idempotency_key("doc:1", "x")


def test_expiry_defaults_to_half_an_hour():
    moment = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

    assert expiry_from(moment) == moment + DEFAULT_APPROVAL_TTL
    assert expiry_from(moment, timedelta(minutes=5)) == moment + timedelta(minutes=5)


def test_naive_timestamps_are_read_as_utc():
    naive = datetime(2026, 9, 14, 12, 0)

    assert as_utc(naive) == datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    assert as_utc(as_utc(naive)) == as_utc(naive)
