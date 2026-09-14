# EvidenceFlow

An AI document intake and approval workbench. It extracts typed data from an
invoice, keeps the source evidence for every field, validates the consequential
parts with ordinary code, requires human approval bound to a specific version,
and writes the approved record to a mock CRM exactly once.

The model proposes. Application code decides.

```
synthetic invoice -> typed extraction (with evidence) -> deterministic validation
  -> evidence review -> version-bound approval -> idempotent mock-CRM write
```

Synthetic data only. No real client documents are in this repository.

## Status

Weeks 1-2 of six are complete: the typed extraction contract, verified evidence,
the append-only event log, the provider boundary, deterministic business
validation, and a 20-document evaluation with hand-written ground truth.
Approval, the idempotent write, durable recovery, and the causal evaluation
follow. See [docs/PLAN.md](docs/PLAN.md) and [evals/report.md](evals/report.md).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 71 tests, no API key required
python scripts/demo.py    # extracts the five sample invoices, prints the evidence
python evals/run.py       # replays the 20-document dataset, regenerates the report
```

Every deterministic test runs against a fake provider. A real provider call is
opt-in and never needed to verify behaviour.

## Live extraction

```bash
cp .env.example .env      # set OPENAI_API_KEY, pin EVIDENCEFLOW_OPENAI_MODEL
python scripts/demo.py --provider openai
```

The model snapshot is pinned by configuration, never a floating alias, so results
stay reproducible.

## API

```bash
uvicorn app.api.app:create_app --factory --reload
```

| Method | Path                            | Purpose                                     |
|--------|---------------------------------|---------------------------------------------|
| POST   | `/documents`                    | store an invoice's text                     |
| POST   | `/documents/{id}/extract`       | extract, then validate                      |
| GET    | `/documents/{id}`               | draft, evidence, validation, event trail    |
| GET    | `/health`                       | liveness                                    |

## Sample output

```
=== inv_001_acme.txt -> extracted ===
  INV-2026-0001  ACME Supplies Ltd
  507.60 GBP  2026-03-04
  payload_hash 0c05e7b4e66e  0ms
    [line  6] invoice_number: 'Invoice Number: INV-2026-0001'
    [line  1] supplier: 'ACME SUPPLIES LTD'
    [line 16] total: 'Total                                              507.60'
```

Each line is a span the application located in the source document, not a
position the model asserted. See [docs/architecture.md](docs/architecture.md).

## Evaluation

Twenty synthetic documents, fifteen of them deliberately hard: a date that is
day-first or month-first, a settlement discount below the line items, per-line
VAT columns, one minor unit of rounding drift, totals split across a page break,
a euro sign under a USD header, a redelivered invoice number, a credit note, and
a document whose printed total does not add up.

Ground truth is hand-written. Three fields are recorded as having no correct
answer at all, because the document contradicts itself — those are review work by
definition, not extraction errors.

Twelve of the twenty produce output the schema accepts and ordinary code refuses.
Valid JSON is not a valid business outcome.

## Layout

```
app/
  api/           HTTP surface
  domain/        schema, evidence verification, event and status vocabulary
  providers/     provider protocol, fake provider, OpenAI Responses adapter
  repositories/  SQLAlchemy models and data access
  services/      extraction and validation orchestration
tests/
  contract/      schema, evidence, and provider-adapter behaviour
  integration/   the slice through persistence and HTTP
  fixtures/      twenty synthetic invoices and their simulated drafts
evals/
  dataset.jsonl  hand-written ground truth and expected routing
  run.py         replays the dataset and regenerates report.md
docs/            plan, architecture
scripts/demo.py  runnable vertical slice
```
