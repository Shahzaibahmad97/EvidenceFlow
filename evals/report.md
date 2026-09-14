# Evaluation v1 — deterministic validation

Generated 2026-09-14 19:05 UTC from `evals/dataset.jsonl` via the `fake` provider.
Regenerate with `python evals/run.py`.

## Headline

- Documents: **20** (5 routine, 15 hard)
- Field accuracy: **123/123** (100%)
- Routed as the hand-written label expects: **20/20** (100%)
- Blocking rules matched the label: **20/20**
- Reached `validated`: **8/20** — 4 to review, 6 failed, 2 rejected at the schema boundary

Field accuracy is scored only where a correct answer exists. 3 field(s) are marked unscorable because the document itself is ambiguous or self-contradictory — those are review work by definition, not extraction errors.

## By difficulty

| Cohort | Documents | Field accuracy | Routed as expected | Reached validated |
|---|---|---|---|---|
| routine | 5 | 35/35 (100%) | 5/5 | 5/5 |
| hard | 15 | 88/88 (100%) | 15/15 | 3/15 |

## Per document

| Document | Expected | Actual | Fields | Blocking rules |
|---|---|---|---|---|
| `inv_001_acme` | validated | validated | 7/7 | — |
| `inv_002_northwind` | validated | validated | 7/7 | — |
| `inv_003_bluepeak` | validated | validated | 7/7 | — |
| `inv_004_meridian` | validated | validated | 7/7 | — |
| `inv_005_calder` | validated | validated | 7/7 | — |
| `fail_missing_invoice_number` | extraction_failed | extraction_failed | n/a | — |
| `fail_bad_currency` | extraction_failed | extraction_failed | n/a | — |
| `fail_unverifiable_quote` | needs_review | needs_review | 7/7 | `evidence_verified` |
| `adv_ambiguous_date` | needs_review | needs_review | 6/6 | `issue_date_unambiguous` |
| `adv_line_discount` | validated | validated | 7/7 | — |
| `adv_document_discount` | fail | fail | 7/7 | `line_items_sum_to_subtotal` |
| `adv_per_line_tax` | fail | fail | 7/7 | `line_item_arithmetic`, `line_items_sum_to_subtotal` |
| `adv_rounding_drift` | needs_review | needs_review | 7/7 | `subtotal_plus_tax_equals_total` |
| `adv_multipage_subtotal` | validated | validated | 7/7 | — |
| `adv_currency_mismatch` | needs_review | needs_review | 6/6 | `currency_agrees_with_source` |
| `adv_duplicate_number` | fail | fail | 7/7 | `invoice_number_not_duplicate` |
| `adv_credit_note` | validated | validated | 7/7 | — |
| `adv_credit_note_mis_signed` | fail | fail | 7/7 | `line_items_sum_to_subtotal`, `credit_note_consistent` |
| `adv_totals_dont_add` | fail | fail | 6/6 | `subtotal_plus_tax_equals_total` |
| `adv_unsupported_currency` | fail | fail | 7/7 | `supported_currency` |

## Schema-valid, business-invalid

10 of 20 documents produced output the model's own schema accepts and that ordinary code refused. This is the case the project exists to make: valid JSON is not a valid business outcome.

**`fail_unverifiable_quote`** — The subtotal quote paraphrases the document. Unverifiable evidence, so the value is not accepted.

- Routed to `needs_review` by `evidence_verified`

**`adv_ambiguous_date`** — 03/04/2026 is day-first or month-first; no other date in the document disambiguates it, so a human must decide.

- Routed to `needs_review` by `issue_date_unambiguous`
- No correct answer exists for: issue_date

**`adv_document_discount`** — The settlement discount sits below the line items. Captured lines sum to 1200.00, subtotal is 1140.00. Schema-valid, arithmetically incoherent.

- Routed to `fail` by `line_items_sum_to_subtotal`

**`adv_per_line_tax`** — Per-line VAT columns. The model took the gross column as the line amount, so lines sum to 636.00 against a 530.00 subtotal.

- Routed to `fail` by `line_item_arithmetic`, `line_items_sum_to_subtotal`

**`adv_rounding_drift`** — 412.55 + 78.38 = 490.93, printed as 490.94. One minor unit of drift: a reviewer decides, not a hard reject.

- Routed to `needs_review` by `subtotal_plus_tax_equals_total`

**`adv_currency_mismatch`** — Header says USD, every amount is prefixed with a euro sign. The document contradicts itself; no extraction is correct.

- Routed to `needs_review` by `currency_agrees_with_source`
- No correct answer exists for: currency

**`adv_duplicate_number`** — A second delivery of INV-2026-0001. Every field is extracted correctly and the document must still be blocked.

- Routed to `fail` by `invoice_number_not_duplicate`

**`adv_credit_note_mis_signed`** — The credit note prints its line amount unsigned. A negative total with a positive line is not a coherent record.

- Routed to `fail` by `line_items_sum_to_subtotal`, `credit_note_consistent`

**`adv_totals_dont_add`** — The printed total is wrong on the document itself: 255.00 + 51.00 = 306.00. Faithful extraction of a wrong document.

- Routed to `fail` by `subtotal_plus_tax_equals_total`
- No correct answer exists for: total

**`adv_unsupported_currency`** — Perfectly extracted, outside the supported currency set. Correct extraction is not authorization to write.

- Routed to `fail` by `supported_currency`

## Label mismatches

None. Every document routed the way its hand-written label said it should.

## What this does not measure

- Ground truth is hand-written, but the documents are synthetic and written by the same person who wrote the rules. Accuracy here is a floor on difficulty, not a forecast of live performance.
- The fake provider replays a fixed payload per document, so this run measures the validation layer, not model quality. Week 5 adds held-out documents and live runs.
- No latency, token, or cost figure is reported: the deterministic provider has no cost, and reporting one would be theatre.
