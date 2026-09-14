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

All six weeks are complete. Start with the
[case study](docs/case-study.md) for what was built and what it measures, the
[evaluation report](evals/report.md) for the numbers, and
[docs/runbook.md](docs/runbook.md) for how it recovers.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                        # 180 tests, no API key required
python scripts/demo.py        # extracts the five sample invoices, prints the evidence
python scripts/demo_approval.py  # approval, idempotent write, twenty replays
python scripts/demo_recovery.py  # 503, worker death mid-write, recovery, one record
python evals/run.py           # replays all 30 documents, regenerates the report
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

## Running the whole thing

```bash
docker compose up
```

API and worker as separate services against Postgres. The review screen is at
<http://localhost:8000/review>, seeded with all thirty synthetic documents.

Or, without Docker:

```bash
EVIDENCEFLOW_SEED_ON_START=true EVIDENCEFLOW_RUN_WORKER=true \
  uvicorn app.api.app:create_app --factory --reload
```

## API

| Method | Path                            | Purpose                                     |
|--------|---------------------------------|---------------------------------------------|
| POST   | `/documents`                    | store an invoice's text                     |
| POST   | `/documents/{id}/extract`       | extract, then validate                      |
| POST   | `/documents/{id}/approve`       | approve the current version (`X-Actor`)     |
| POST   | `/documents/{id}/write`         | write to the mock CRM, once per version     |
| POST   | `/documents/{id}/jobs`          | queue extraction or a write for the worker  |
| GET    | `/jobs/{id}`                    | job status, attempts, failure kind          |
| GET    | `/jobs/review`                  | jobs a person needs to look at              |
| GET    | `/documents/{id}`               | draft, evidence, validation, approval, events |
| GET    | `/health`                       | liveness                                    |
| GET    | `/review`                       | review screen: evidence, validation, approval |

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

Thirty synthetic documents — twenty for development, ten held out and never used
to tune a rule, a threshold or the prompt. Twenty-four are deliberately hard: a
date that is day-first or month-first, a settlement discount below the line
items, per-line VAT columns, one minor unit of rounding drift, totals split
across a page break, a euro sign under a USD header, a prior balance printed
below the total, a redelivered invoice number, a credit note, and a document
whose printed total does not add up.

Ground truth is hand-written. Five fields are recorded as having no correct
answer at all, because the document contradicts itself — those are review work by
definition, not extraction errors.

Seventeen of the thirty produce output the schema accepts and ordinary code
refuses. Valid JSON is not a valid business outcome.

Each blocked document is labelled by its **earliest causal error** — `selection`,
`completeness`, `truthfulness` or `postcondition` — so the root cause is counted
once rather than the damage downstream of it. Twelve are postcondition failures:
the model was right and the answer was still no.

Cost per accepted outcome includes reviewer time, not tokens alone. At the stated
assumptions reviewer time is 99% of it, which is the point of measuring it.

See [evals/report.md](evals/report.md).

## Approval and replay protection

```
$ python scripts/demo_approval.py
1. extracted and validated -> validated
   payload_hash 0c05e7b4e66e82c3
2. approved by reviewer@example.com -> approved
   idempotency key affce170c7673d5b
3. wrote CRM-00001 -> written
4. twenty replays -> 1 destination call(s), 1 record(s)
5. corrected document, write refused -> approval_missing
```

The idempotency key is derived on the server from the document id and the
approved payload hash. `crm_write.idempotency_key` is `UNIQUE`, the mock
destination deduplicates on the same key, and the document transition to
`written` is one guarded `UPDATE`. Eight concurrent writers produce one record.

## Failure recovery

```
$ python scripts/demo_recovery.py
1. extract job succeeded, document validated
2. destination returned 503 -> job pending, attempt 1
   retry scheduled, classified transient: crm_unavailable: 503 from destination
3. worker claimed job (attempt 2) then died mid-write
4. new worker reclaimed the expired lease -> succeeded, attempt 3
5. document status written, destination records 1
6. audit trail survived: ... write_attempted -> write_failed -> write_attempted -> write_succeeded
```

Jobs live in a database table, claimed by a guarded `UPDATE` and held by a lease.
No broker, no second service. Retries are classified by exception type, never by
string matching, and anything unrecognised is treated as permanent. See
[docs/runbook.md](docs/runbook.md).

## Review screen

`/review` lists every document with its status and blocking rules. A document page
shows the source with each verified evidence span highlighted, the proposed
fields, all eleven validation results, and the event trail.

The screen is a view over server state, never a source of truth. The approve form
carries the payload hash it was rendered with, and the server refuses it if the
document has changed since — a stale tab cannot approve a version nobody read.

## Layout

```
app/
  api/           HTTP surface
  domain/        schema, evidence verification, event and status vocabulary
  providers/     provider protocol, fake provider, OpenAI Responses adapter
  repositories/  SQLAlchemy models and data access
  services/      extraction, validation, approval and write orchestration
  workflows/     durable job queue and the worker
tests/
  contract/      schema, evidence, and provider-adapter behaviour
  integration/   the slice through persistence and HTTP
  fixtures/      twenty synthetic invoices and their simulated drafts
evals/
  dataset.jsonl  hand-written ground truth and expected routing
  run.py         replays the dataset and regenerates report.md
docs/            case study, architecture, runbook, deployment, demo script
scripts/         runnable demos: extraction, approval, recovery
Dockerfile, docker-compose.yml
```
