from __future__ import annotations

from evals.run import SPLITS, load, load_splits, run

EXPECTED = {"dev": 20, "held_out": 10}
SCORED_FIELDS = 7


def test_both_splits_are_complete_and_disjoint():
    dev, held_out = load("dev"), load("held_out")

    assert (len(dev), len(held_out)) == (EXPECTED["dev"], EXPECTED["held_out"])
    assert not {entry["id"] for entry in dev} & {entry["id"] for entry in held_out}
    for split, entries in (("dev", dev), ("held_out", held_out)):
        documents = SPLITS[split][1]
        assert all((documents / entry["document"]).exists() for entry in entries)
        assert all(entry["notes"].strip() for entry in entries)
        assert all(set(entry["ground_truth"]) == set(load(split)[0]["ground_truth"]) for entry in entries)


def test_the_held_out_documents_are_never_used_to_tune():
    held_out = load("held_out")

    assert {entry["split"] for entry in held_out} == {"held_out"}
    assert sum(entry["expected_outcome"] == "validated" for entry in held_out) == 5


def test_every_document_routes_and_labels_as_written():
    result = run(load_splits("all"), "fake", fallback=False, name="baseline")

    mismatches = [
        f"{row.id}: {row.outcome}/{row.label}"
        for row in result.rows
        if not row.routed_as_expected or not row.labelled_as_expected
    ]

    assert mismatches == []


def test_the_pipeline_writes_each_accepted_document_exactly_once():
    result = run(load_splits("all"), "fake", fallback=False, name="baseline")

    assert result.accepted > 0
    assert result.duplicate_writes == 0
    assert result.destination_calls == result.destination_records
    assert all(row.external_id for row in result.rows if row.accepted)


def test_a_clean_run_records_no_retries():
    result = run(load_splits("dev"), "fake", fallback=False, name="baseline")

    assert sum(row.retries for row in result.rows) == 0


def test_the_value_fallback_accepts_documents_the_baseline_refuses():
    entries = load_splits("all")
    baseline = run(entries, "fake", fallback=False, name="baseline")
    variant = run(entries, "fake", fallback=True, name="value-fallback")

    newly_accepted = {
        after.id
        for before, after in zip(baseline.rows, variant.rows, strict=True)
        if after.accepted and not before.accepted
    }

    assert newly_accepted == {"fail_unverifiable_quote", "h_004_paraphrased_total"}


def test_the_dataset_covers_the_intended_failure_modes():
    rules = {
        rule
        for split in SPLITS
        for entry in load(split)
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


def test_every_causal_label_appears_in_the_dataset():
    labels = {
        entry["expected_label"]
        for split in SPLITS
        for entry in load(split)
        if entry["expected_label"]
    }

    assert labels == {"selection", "completeness", "truthfulness", "postcondition"}
