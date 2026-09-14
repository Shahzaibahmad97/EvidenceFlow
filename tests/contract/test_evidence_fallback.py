from __future__ import annotations

from app.domain.evidence import verify_draft
from app.domain.schema import InvoiceDraft

NAME = "fail_unverifiable_quote"


def _results(fixtures, **kwargs):
    draft = InvoiceDraft.model_validate(fixtures.payload(NAME))
    return {
        result.field: result
        for result in verify_draft(draft, fixtures.text(NAME), **kwargs)
    }


def test_the_fallback_is_off_by_default(fixtures):
    assert not _results(fixtures)["subtotal"].verified


def test_the_fallback_resolves_the_value_and_says_so(fixtures):
    subtotal = _results(fixtures, allow_value_fallback=True)["subtotal"]

    assert subtotal.verified
    assert subtotal.derived_from_value


def test_a_verified_quote_is_never_marked_derived(fixtures):
    total = _results(fixtures, allow_value_fallback=True)["total"]

    assert total.verified
    assert not total.derived_from_value


def test_the_fallback_still_refuses_a_value_absent_from_the_source(fixtures):
    payload = fixtures.payload(NAME)
    payload["subtotal"] = {"value": "999.99", "quote": "invented prose"}
    draft = InvoiceDraft.model_validate(payload)

    results = verify_draft(draft, fixtures.text(NAME), allow_value_fallback=True)

    assert not next(r for r in results if r.field == "subtotal").verified
