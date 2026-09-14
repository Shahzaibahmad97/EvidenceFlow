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

Week 1 of six is complete: the typed extraction contract, verified evidence, the
append-only event log, and the provider boundary. Validation, approval, the
idempotent write, durable recovery, and the evaluation report follow.
See [docs/PLAN.md](docs/PLAN.md).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                    # 38 tests, no API key required
python scripts/demo.py    # extracts all five sample invoices, prints the evidence
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
| POST   | `/documents/{id}/extract`       | run an extraction attempt                   |
| GET    | `/documents/{id}`               | draft, evidence spans, and the event trail  |
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

## Layout

```
app/
  api/           HTTP surface
  domain/        schema, evidence verification, event and status vocabulary
  providers/     provider protocol, fake provider, OpenAI Responses adapter
  repositories/  SQLAlchemy models and data access
  services/      extraction orchestration
tests/
  contract/      schema, evidence, and provider-adapter behaviour
  integration/   the slice through persistence and HTTP
  fixtures/      five sample invoices and three failure cases
docs/            plan, architecture
scripts/demo.py  runnable vertical slice
```
