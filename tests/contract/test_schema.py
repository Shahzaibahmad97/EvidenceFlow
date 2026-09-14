from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.schema import SCHEMA_VERSION, InvoiceDraft


def test_parses_money_and_dates_without_floats(fixtures):
    draft = InvoiceDraft.model_validate(fixtures.payload("inv_001_acme"))

    assert draft.total.value == Decimal("507.60")
    assert draft.issue_date.value == date(2026, 3, 4)
    assert draft.line_items[0].amount == Decimal("245.00")


def test_missing_required_field_is_rejected(fixtures):
    with pytest.raises(ValidationError) as excinfo:
        InvoiceDraft.model_validate(fixtures.payload("fail_missing_invoice_number"))

    assert "invoice_number" in str(excinfo.value)


def test_currency_must_be_a_three_letter_code(fixtures):
    with pytest.raises(ValidationError) as excinfo:
        InvoiceDraft.model_validate(fixtures.payload("fail_bad_currency"))

    assert "currency" in str(excinfo.value)


def test_evidence_quote_may_not_be_empty(fixtures):
    payload = fixtures.payload("inv_001_acme")
    payload["supplier"]["quote"] = ""

    with pytest.raises(ValidationError):
        InvoiceDraft.model_validate(payload)


def test_payload_hash_is_stable_across_key_order(fixtures):
    payload = fixtures.payload("inv_002_northwind")
    reordered = dict(reversed(list(payload.items())))

    assert (
        InvoiceDraft.model_validate(payload).payload_hash()
        == InvoiceDraft.model_validate(reordered).payload_hash()
    )


def test_payload_hash_changes_with_any_value(fixtures):
    payload = fixtures.payload("inv_002_northwind")
    original = InvoiceDraft.model_validate(payload).payload_hash()
    payload["total"]["value"] = "512.90"

    assert InvoiceDraft.model_validate(payload).payload_hash() != original


def test_evidenced_fields_excludes_line_items(fixtures):
    draft = InvoiceDraft.model_validate(fixtures.payload("inv_001_acme"))

    assert set(draft.evidenced_fields()) == {
        "invoice_number",
        "supplier",
        "currency",
        "issue_date",
        "subtotal",
        "tax",
        "total",
    }
    assert SCHEMA_VERSION == "1.0.0"
