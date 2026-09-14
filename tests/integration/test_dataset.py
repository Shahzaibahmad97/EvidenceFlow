from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))

from run import DOCUMENTS, load_dataset, run  # noqa: E402

EXPECTED_SIZE = 20


def test_dataset_is_complete_and_unique():
    entries = load_dataset()
    ids = [entry["id"] for entry in entries]

    assert len(entries) == EXPECTED_SIZE
    assert len(set(ids)) == EXPECTED_SIZE
    assert all((DOCUMENTS / entry["document"]).exists() for entry in entries)
    assert all(entry["notes"].strip() for entry in entries)


def test_every_document_routes_the_way_its_label_says():
    mismatches = [
        f"{row.id}: expected {row.expected_outcome}, got {row.outcome} {row.error}"
        for row in run("fake")
        if not row.routed_as_expected
    ]

    assert mismatches == []


def test_hard_cohort_covers_the_intended_failure_modes():
    rules = {
        rule
        for entry in load_dataset()
        for rule in entry["expected_blocking_rules"]
    }

    assert rules >= {
        "line_items_sum_to_subtotal",
        "subtotal_plus_tax_equals_total",
        "supported_currency",
        "currency_agrees_with_source",
        "issue_date_unambiguous",
        "invoice_number_not_duplicate",
        "credit_note_consistent",
        "evidence_verified",
    }
