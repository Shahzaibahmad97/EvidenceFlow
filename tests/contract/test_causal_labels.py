from __future__ import annotations

import pytest

from evals.labels import CausalLabel, label_blocking_rules, label_extraction_failure


def test_a_missing_field_is_a_completeness_failure():
    assert label_extraction_failure("invoice_number: Field required") is CausalLabel.COMPLETENESS


def test_a_wrong_value_is_a_selection_failure():
    detail = "currency.value: String should match pattern '^[A-Z]{3}$'"

    assert label_extraction_failure(detail) is CausalLabel.SELECTION


def test_unverifiable_evidence_outranks_everything_downstream():
    rules = ["evidence_verified", "line_items_sum_to_subtotal", "supported_currency"]

    assert label_blocking_rules(rules) is CausalLabel.TRUTHFULNESS


def test_a_mis_signed_credit_note_is_a_postcondition_not_a_sum_error():
    rules = ["line_items_sum_to_subtotal", "credit_note_consistent"]

    assert label_blocking_rules(rules) is CausalLabel.POSTCONDITION


def test_misread_lines_are_a_selection_error_once():
    rules = ["line_item_arithmetic", "line_items_sum_to_subtotal"]

    assert label_blocking_rules(rules) is CausalLabel.SELECTION


@pytest.mark.parametrize(
    "rule",
    [
        "supported_currency",
        "invoice_number_not_duplicate",
        "currency_agrees_with_source",
        "issue_date_unambiguous",
        "subtotal_plus_tax_equals_total",
    ],
)
def test_faithful_extraction_that_cannot_be_written_is_a_postcondition(rule):
    assert label_blocking_rules([rule]) is CausalLabel.POSTCONDITION


def test_a_clean_document_has_no_label():
    assert label_blocking_rules([]) is None
