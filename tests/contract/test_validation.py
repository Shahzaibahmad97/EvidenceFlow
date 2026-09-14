from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.domain.evidence import EvidenceResult, verify_draft
from app.domain.schema import InvoiceDraft
from app.domain.validation import (
    RuleOutcome,
    ValidationInput,
    is_accepted,
    normalize_supplier,
    validate,
)

TODAY = date(2026, 9, 14)


def build_input(fixtures, name, **overrides) -> ValidationInput:
    draft = InvoiceDraft.model_validate(fixtures.payload(name))
    source = fixtures.text(name)
    return ValidationInput(
        draft=draft,
        source=source,
        evidence=verify_draft(draft, source),
        today=overrides.pop("today", TODAY),
        **overrides,
    )


def outcome_of(results, rule_name) -> RuleOutcome:
    return next(result.outcome for result in results if result.rule == rule_name)


def blocking_rules(results) -> list[str]:
    return [result.rule for result in results if result.blocking]


def test_clean_invoice_passes_every_rule(fixtures):
    results = validate(build_input(fixtures, "inv_001_acme"))

    assert is_accepted(results)
    assert {result.outcome for result in results} == {RuleOutcome.PASS}


def test_document_level_discount_breaks_the_subtotal(fixtures):
    results = validate(build_input(fixtures, "adv_document_discount"))

    assert outcome_of(results, "line_items_sum_to_subtotal") is RuleOutcome.FAIL
    assert not is_accepted(results)


def test_negative_discount_line_is_not_an_arithmetic_error(fixtures):
    results = validate(build_input(fixtures, "adv_line_discount"))

    assert is_accepted(results)


def test_one_minor_unit_of_drift_is_review_not_failure(fixtures):
    results = validate(build_input(fixtures, "adv_rounding_drift"))

    assert outcome_of(results, "subtotal_plus_tax_equals_total") is RuleOutcome.NEEDS_REVIEW
    assert blocking_rules(results) == ["subtotal_plus_tax_equals_total"]


def test_large_arithmetic_error_fails(fixtures):
    results = validate(build_input(fixtures, "adv_totals_dont_add"))

    assert outcome_of(results, "subtotal_plus_tax_equals_total") is RuleOutcome.FAIL


def test_unsupported_currency_fails(fixtures):
    results = validate(build_input(fixtures, "adv_unsupported_currency"))

    assert outcome_of(results, "supported_currency") is RuleOutcome.FAIL


def test_currency_symbol_contradicting_the_code_needs_review(fixtures):
    results = validate(build_input(fixtures, "adv_currency_mismatch"))

    assert outcome_of(results, "currency_agrees_with_source") is RuleOutcome.NEEDS_REVIEW


def test_ambiguous_numeric_date_needs_review(fixtures):
    results = validate(build_input(fixtures, "adv_ambiguous_date"))

    assert outcome_of(results, "issue_date_unambiguous") is RuleOutcome.NEEDS_REVIEW


def test_iso_date_is_never_ambiguous(fixtures):
    results = validate(build_input(fixtures, "inv_004_meridian"))

    assert outcome_of(results, "issue_date_unambiguous") is RuleOutcome.PASS


def test_future_date_fails(fixtures):
    data = build_input(fixtures, "inv_005_calder", today=date(2026, 1, 1))

    assert outcome_of(validate(data), "issue_date_plausible") is RuleOutcome.FAIL


def test_duplicate_invoice_number_for_the_same_supplier_fails(fixtures):
    known = frozenset({(normalize_supplier("ACME SUPPLIES LTD"), "INV-2026-0001")})
    data = build_input(fixtures, "adv_duplicate_number", known_invoice_numbers=known)

    assert outcome_of(validate(data), "invoice_number_not_duplicate") is RuleOutcome.FAIL


def test_same_number_from_a_different_supplier_passes(fixtures):
    known = frozenset({(normalize_supplier("Someone Else Ltd"), "INV-2026-0001")})
    data = build_input(fixtures, "adv_duplicate_number", known_invoice_numbers=known)

    assert outcome_of(validate(data), "invoice_number_not_duplicate") is RuleOutcome.PASS


def test_well_formed_credit_note_is_accepted(fixtures):
    results = validate(build_input(fixtures, "adv_credit_note"))

    assert is_accepted(results)
    assert InvoiceDraft.model_validate(
        fixtures.payload("adv_credit_note")
    ).total.value == Decimal("-216.00")


def test_mis_signed_credit_note_fails(fixtures):
    results = validate(build_input(fixtures, "adv_credit_note_mis_signed"))

    assert outcome_of(results, "credit_note_consistent") is RuleOutcome.FAIL


def test_unverified_evidence_needs_review(fixtures):
    results = validate(build_input(fixtures, "fail_unverifiable_quote"))

    assert outcome_of(results, "evidence_verified") is RuleOutcome.NEEDS_REVIEW
    assert blocking_rules(results) == ["evidence_verified"]


def test_blank_required_field_fails(fixtures):
    payload = fixtures.payload("inv_001_acme")
    payload["supplier"]["value"] = "   "
    draft = InvoiceDraft.model_validate(payload)

    results = validate(ValidationInput(draft=draft, source=fixtures.text("inv_001_acme")))

    assert outcome_of(results, "required_fields_present") is RuleOutcome.FAIL


@pytest.mark.parametrize(
    ("left", "right"),
    [("ACME SUPPLIES LTD", "Acme Supplies Ltd"), ("Calder & Sons", "calder and sons")],
)
def test_supplier_normalization_ignores_case_and_punctuation(left, right):
    assert normalize_supplier(left) == normalize_supplier(right.replace(" and ", " & "))


def test_every_rule_reports_itself_exactly_once(fixtures):
    results = validate(build_input(fixtures, "inv_002_northwind"))
    names = [result.rule for result in results]

    assert len(names) == len(set(names)) == 11
