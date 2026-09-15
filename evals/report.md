# Evaluation v2 — causal labels and cost per accepted outcome

Generated 2026-09-15 02:49 UTC. Provider `fake`, model `fake-extractor-1`, prompt `ccbc7498ddd41343`.
Regenerate with `python evals/run.py`.

Runs marked `fake` are **replayed** from committed fixtures, not live model calls. Live runs use `--provider openai` and are labelled as such in the header above.

## Headline

- Documents: **30** — 20 development, 10 held out
- Accepted and written: **13/30** (43%)
- Field accuracy: **191/191** (100%)
- Routed as the hand-written label expects: **30/30**
- Causal label matched the hand-written label: **30/30**
- Duplicate destination records: **0**
- Destination calls: 13 for 13 records
- Retries: **0**
- Extraction latency: p50 0 ms, p95 0 ms — a replayed run has no model call to time
- Tokens: 2,947 in, 5,822 out

## Cost per accepted outcome

Every figure below rests on stated assumptions, not measurements:

- model input $2.50 per million tokens
- model output $10.00 per million tokens
- reviewer $35.00 per hour
- 4 minutes of review per flagged document

| Component | Amount |
|---|---|
| Model | $0.0656 |
| Reviewer (17 documents) | $39.6667 |
| **Total** | **$39.7323** |
| Accepted records | 13 |
| **Cost per accepted record** | **$3.0563** |

Reviewer time dominates, and that is the finding. A cost figure quoting only tokens would be smaller, more flattering, and wrong.

## By split

| Split | Documents | Field accuracy | Routed as expected | Labelled as expected | Accepted |
|---|---|---|---|---|---|
| dev | 20 | 123/123 (100%) | 20/20 | 20/20 | 8/20 |
| held_out | 10 | 68/68 (100%) | 10/10 | 10/10 | 5/10 |

## By difficulty

| Cohort | Documents | Field accuracy | Accepted | Sent to a person |
|---|---|---|---|---|
| routine | 6 | 42/42 (100%) | 6/6 | 0/6 |
| hard | 24 | 149/149 (100%) | 7/24 | 17/24 |

## Earliest causal error

Each blocked document is labelled by its root cause, not by the damage that followed it. A document whose lines were mis-read *and* whose totals then failed to add up is a selection error, once.

| Label | Documents | Meaning |
|---|---|---|
| `selection` | 4 | the model took the wrong value from the document |
| `completeness` | 1 | a required field was not there to take |
| `truthfulness` | 2 | the evidence offered does not appear in the source |
| `postcondition` | 10 | extraction was faithful; the record still cannot be written |

10 of 17 blocked documents are postcondition failures. The model was right and the answer was still no — because the document contradicts itself, repeats an earlier invoice, or falls outside policy. No prompt change addresses those.

## Per document

| Document | Split | Expected | Actual | Label | Fields | Jobs | Retries |
|---|---|---|---|---|---|---|---|
| `inv_001_acme` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `inv_002_northwind` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `inv_003_bluepeak` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `inv_004_meridian` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `inv_005_calder` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `fail_missing_invoice_number` | dev | extraction_failed | extraction_failed | completeness | n/a | 1 | 0 |
| `fail_bad_currency` | dev | extraction_failed | extraction_failed | selection | n/a | 1 | 0 |
| `fail_unverifiable_quote` | dev | needs_review | needs_review | truthfulness | 7/7 | 1 | 0 |
| `adv_ambiguous_date` | dev | needs_review | needs_review | postcondition | 6/6 | 1 | 0 |
| `adv_line_discount` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `adv_document_discount` | dev | fail | fail | selection | 7/7 | 1 | 0 |
| `adv_per_line_tax` | dev | fail | fail | selection | 7/7 | 1 | 0 |
| `adv_rounding_drift` | dev | needs_review | needs_review | postcondition | 7/7 | 1 | 0 |
| `adv_multipage_subtotal` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `adv_currency_mismatch` | dev | needs_review | needs_review | postcondition | 6/6 | 1 | 0 |
| `adv_duplicate_number` | dev | fail | fail | postcondition | 7/7 | 1 | 0 |
| `adv_credit_note` | dev | validated | validated | — | 7/7 | 2 | 0 |
| `adv_credit_note_mis_signed` | dev | fail | fail | postcondition | 7/7 | 1 | 0 |
| `adv_totals_dont_add` | dev | fail | fail | postcondition | 6/6 | 1 | 0 |
| `adv_unsupported_currency` | dev | fail | fail | postcondition | 7/7 | 1 | 0 |
| `h_001_wren` | held_out | validated | validated | — | 7/7 | 2 | 0 |
| `h_002_two_line_supplier` | held_out | validated | validated | — | 7/7 | 2 | 0 |
| `h_003_free_item` | held_out | validated | validated | — | 7/7 | 2 | 0 |
| `h_004_paraphrased_total` | held_out | needs_review | needs_review | truthfulness | 7/7 | 1 | 0 |
| `h_005_prior_balance` | held_out | fail | fail | selection | 7/7 | 1 | 0 |
| `h_006_textual_date` | held_out | validated | validated | — | 7/7 | 2 | 0 |
| `h_007_ambiguous_date` | held_out | needs_review | needs_review | postcondition | 6/6 | 1 | 0 |
| `h_008_symbol_disagrees` | held_out | needs_review | needs_review | postcondition | 6/6 | 1 | 0 |
| `h_009_thousands_separator` | held_out | validated | validated | — | 7/7 | 2 | 0 |
| `h_010_redelivered` | held_out | fail | fail | postcondition | 7/7 | 1 | 0 |

## Held-out documents

These ten were written after the rules were fixed and were never used to tune them. No rule, threshold, or prompt was changed after seeing these results.

All ten routed and labelled as their hand-written labels said they would. That is a real result and a narrow one: the held-out set shares an author and a generator with the development set.

## Label mismatches

None.

## Attempted improvement: fall back to the field value when a quote cannot be found

**Change.** When a model-supplied quote is not present in the source, look for the extracted *value* instead and accept the span it lands on.

**Result.** Accepted records 13 -> 15. Documents that changed outcome: 2 (fail_unverifiable_quote, h_004_paraphrased_total)

**Decision: rejected.** It buys acceptance by giving up the guarantee the project exists to make. A quote the model invented is not evidence, and finding the number somewhere else in the document does not make it so — the number appears in a total, a line item and a payment slip, and the fallback cannot tell which one the model meant. Every document it newly accepted (fail_unverifiable_quote, h_004_paraphrased_total) would have been accepted on evidence nobody can check.

The code path stays in the repository, off by default, because the experiment is part of the evidence. `allow_value_fallback` is never set in production.

## What this does not measure

- The documents are synthetic and share an author with the rules. Accuracy here is a statement about the difficulty of this set, not a forecast of live performance.
- A `fake` run replays committed payloads, so it measures the validation, approval and write layers rather than model quality. Only a live run measures the model.
- Retries are zero in a clean run because nothing failed. The retry and recovery paths are exercised by the test suite and by `scripts/demo_recovery.py`, not here.
- Reviewer minutes are assumed, not observed. Nobody reviewed these documents.
