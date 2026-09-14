"""Earliest causal error for a failed trajectory.

Rules are ordered by how early in the pipeline their cause sits, not by the
order they happen to be evaluated in. The first matching rule wins, so a
document blocked by several rules is labelled by its root cause rather than by
the damage that followed.
"""

from __future__ import annotations

from enum import StrEnum


class CausalLabel(StrEnum):
    SELECTION = "selection"
    COMPLETENESS = "completeness"
    TRUTHFULNESS = "truthfulness"
    POSTCONDITION = "postcondition"


RULE_PRECEDENCE: tuple[tuple[str, CausalLabel], ...] = (
    ("evidence_verified", CausalLabel.TRUTHFULNESS),
    ("required_fields_present", CausalLabel.COMPLETENESS),
    ("credit_note_consistent", CausalLabel.POSTCONDITION),
    ("supported_currency", CausalLabel.POSTCONDITION),
    ("invoice_number_not_duplicate", CausalLabel.POSTCONDITION),
    ("currency_agrees_with_source", CausalLabel.POSTCONDITION),
    ("issue_date_unambiguous", CausalLabel.POSTCONDITION),
    ("issue_date_plausible", CausalLabel.POSTCONDITION),
    ("line_item_arithmetic", CausalLabel.SELECTION),
    ("line_items_sum_to_subtotal", CausalLabel.SELECTION),
    ("subtotal_plus_tax_equals_total", CausalLabel.POSTCONDITION),
)

MISSING_FIELD_MARKERS = ("field required", "missing")


def label_extraction_failure(error_detail: str) -> CausalLabel:
    lowered = (error_detail or "").lower()
    if any(marker in lowered for marker in MISSING_FIELD_MARKERS):
        return CausalLabel.COMPLETENESS
    return CausalLabel.SELECTION


def label_blocking_rules(rules: list[str]) -> CausalLabel | None:
    blocking = set(rules)
    for rule, label in RULE_PRECEDENCE:
        if rule in blocking:
            return label
    return None
