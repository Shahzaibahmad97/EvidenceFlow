from __future__ import annotations

from app.domain.evidence import find_span, verify_draft
from app.domain.schema import InvoiceDraft

SOURCE = "Invoice Number: INV-1\nIssue Date:   2026-03-04\nTotal   99.00\n"


def test_exact_quote_resolves_to_a_span():
    span = find_span(SOURCE, "Invoice Number: INV-1")

    assert SOURCE[span.start : span.end] == "Invoice Number: INV-1"
    assert span.line == 1


def test_whitespace_differences_are_tolerated():
    span = find_span(SOURCE, "Issue Date: 2026-03-04")

    assert SOURCE[span.start : span.end] == "Issue Date:   2026-03-04"
    assert span.line == 2


def test_quote_spanning_a_newline_resolves():
    span = find_span(SOURCE, "INV-1 Issue Date: 2026-03-04")

    assert span.start < span.end
    assert span.line == 1


def test_paraphrased_quote_is_not_found():
    assert find_span(SOURCE, "the total is 99.00") is None


def test_similar_but_not_verbatim_quote_is_not_found():
    assert find_span(SOURCE, "Invoice Number: INV-2") is None


def test_empty_quote_is_not_found():
    assert find_span(SOURCE, "   ") is None


def test_verify_draft_reports_every_evidenced_field(fixtures):
    name = "inv_003_bluepeak"
    draft = InvoiceDraft.model_validate(fixtures.payload(name))

    results = verify_draft(draft, fixtures.text(name))

    assert len(results) == 7
    assert all(result.verified for result in results)


def test_verify_draft_marks_unverifiable_evidence(fixtures):
    name = "fail_unverifiable_quote"
    draft = InvoiceDraft.model_validate(fixtures.payload(name))

    rejected = [r.field for r in verify_draft(draft, fixtures.text(name)) if not r.verified]

    assert rejected == ["subtotal"]
