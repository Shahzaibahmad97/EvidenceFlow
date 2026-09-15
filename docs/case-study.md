# EvidenceFlow

**A tested AI document workflow with evidence, human approval, replay protection,
and cost-per-accepted-outcome evaluation.**

I built a Python AI integration that extracts invoice data into a typed contract,
validates the consequential fields with ordinary code, requires approval bound to
a specific version, survives retries without duplicate writes, and reports quality
and cost against a held-out synthetic evaluation set.

Six weeks, roughly six hours a week. Synthetic data throughout.

## The buyer's problem

A finance team receives invoices as text and re-keys them into an accounting
system. They have seen a demo where a model reads an invoice and fills a form, and
they want it. What they actually need is narrower and harder:

- If the system records a wrong total, someone pays the wrong amount.
- If it records the same invoice twice, someone pays twice.
- If an auditor asks where a number came from, "the model said so" is not an
  answer.
- Nobody will sign off on a system that takes an action they did not approve.

An extraction demo answers none of these. The interesting work is not getting JSON
out of a model. It is deciding what may be done with that JSON.

## Constraints I set

- One document type, one provider, one destination.
- Synthetic data only; no real client documents anywhere in the repository.
- Every deterministic test runs with no API key, so the suite is the proof and a
  model call is never required to check behaviour.
- No OCR, no email intake, no real accounting connector, no autonomous payment.

Naming what is excluded is part of the work. A scope that cannot be stated cannot
be delivered.

## Boundary design

The model owns exactly one thing: turning variable document text into a proposed
`InvoiceDraft`. Everything consequential is ordinary code.

| Concern | Owner |
|---|---|
| Reading a messy document into structure | model |
| Arithmetic, currency policy, required fields, duplicates | application code |
| Whether evidence is real | application code |
| Workflow state and authorisation | application code |
| Idempotency and the destination write | application code and the database |

Four decisions carry the design.

**Evidence is verified, not asserted.** The model does not emit character offsets;
it is unreliable at them, and an offset nobody can check is not evidence. It
returns a verbatim `quote`, and the application locates that quote in the source
and computes the span itself. A quote that cannot be located is rejected and the
field is marked unverified. Provenance becomes checkable by ordinary code, which
is the whole argument.

**Validation is separate from schema validity, and stored separately.** Eleven
pure rules decide whether a draft could be true: line and document arithmetic,
supported currency, agreement between currency symbol and code, date plausibility
and ambiguity, duplicate invoice numbers, evidence, credit-note sign consistency.
They return `pass`, `needs_review`, or `fail`, because one penny of rounding drift
is a reviewer's call and a sixty-pound discrepancy is not.

**Approval binds to content, not to a version number.** The document carries the
hash of the approved payload, and any new extraction clears it. A correction
invalidates a prior approval by construction, not by a check somebody has to
remember to write.

**Idempotency is structural, at both ends.** The key is derived on the server from
the document id and the approved payload hash, length-prefixed before hashing so no pair of ids
can collide by shifting the boundary between them. The key column is `UNIQUE`. The
mock destination deduplicates on the same key, so replay safety holds end to end
rather than only on our side. The document moves to `written` through one guarded
`UPDATE` whose zero-row result rejects a document that left the approved state
mid-flight. There is no read-then-write anywhere in the path.

## Failure tests

200 tests, none of which need an API key. The ones that shaped the design:

- **Twenty replays of an approved write** produce one destination record and one
  destination call.
- **Eight concurrent writers** against a file-backed database produce one record,
  one write row, and one success event.
- **A correction after approval** blocks the write with `approval_missing`.
- **An expired approval** blocks a new write, but a replay of work that already
  succeeded is still a no-op rather than an error. Retrying settled work is not a
  new action.
- **A worker killed mid-write** is reclaimed when its lease expires, completes,
  and produces no second record — with both the failed and the successful attempt
  still in the audit trail.
- **A destination 503** is classified transient and retried with backoff; a 422 is
  classified permanent and goes straight to the review queue on the first attempt.
- **An unrecognised error is treated as permanent.** Retrying something nobody has
  reasoned about is how one failure becomes a storm.
- **Two copies of one invoice** both validate on arrival, and the second is
  refused the moment the first is written — caught by re-validating at approval,
  and by a unique business key at the destination if it ever got that far.

## Verified in containers, not only in tests

Tests prove the logic. They do not prove the thing you deploy, and three of the
defects I found in this project were only visible once it ran as a container:
the image installed the package without its PostgreSQL driver, the HTML templates
were not packaged at all, and the fixture path was derived from the source tree in
a way that resolves elsewhere once installed.

So the stack was run, not assumed:

| Checked | Result |
|---|---|
| Image built from the repository `Dockerfile` | 151 MB, templates and both migrations present inside the running container |
| `migrate` container | applied the schema to PostgreSQL and exited cleanly |
| `api` and `worker` as separate containers | API healthy on its own `HEALTHCHECK`; the worker drained all thirty seeded documents |
| End-to-end suite against the containerised API | **61 of 61** |
| Worker container stopped mid-job, then restarted | job resumed and completed, one destination record |
| Single-process image (`scripts/start.sh`, the shape a free tier runs) | migrations, seeding and an in-process worker on boot; **61 of 61** |
| Same image with the port injected by the host, as a platform does | healthy, seeded, **61 of 61** |
| Destination reconciliation | records, distinct invoices and distinct idempotency keys all equal |

`scripts/e2e_live.py` is the suite. It drives the documents a deployment is
already seeded with, the way a reviewer would, rather than uploading its own.

## Measured results

Thirty synthetic documents: twenty for development, ten held out and never used to
tune a rule, a threshold, or the prompt. Ground truth is hand-written. Five fields
are recorded as having **no correct answer at all**, because the document
contradicts itself — counting those as extraction errors would be dishonest, and
counting them as successes would be worse.

| Measure | Result |
|---|---|
| Accepted and written | 13/30 |
| Field accuracy | 191/191 on scorable fields |
| Routed as the hand-written label expects | 30/30 |
| Causal label matched the hand-written label | 30/30 |
| Duplicate destination records | 0 |
| Held-out documents routed and labelled correctly | 10/10 |

Seventeen documents produced output the schema accepts and ordinary code refused.
Each is labelled by its **earliest causal error**, so a root cause is counted once
rather than the damage that followed it:

| Label | Count |
|---|---|
| `selection` — the model took the wrong value | 4 |
| `completeness` — a required field was not there | 1 |
| `truthfulness` — the evidence offered is not in the source | 2 |
| `postcondition` — extraction was faithful, the record still cannot be written | 12 |

**Twelve of seventeen are postcondition failures.** The model was right and the
answer was still no: the document contradicts itself, repeats an earlier invoice,
or falls outside policy. No prompt change addresses those. That is the single most
useful number in the report, and it is the one an extraction demo can never show.

### Cost per accepted outcome

| Component | Amount |
|---|---|
| Model | $0.07 |
| Reviewer, 17 documents at 4 minutes and $35/hour | $39.67 |
| **Per accepted record** | **$3.06** |

Reviewer time is 99.8% of it. A token-only figure would be around half a cent and
would tell the buyer nothing. Every input here is a stated assumption, not a
measurement; nobody actually reviewed these documents.

### An improvement I rejected

When a model-supplied quote cannot be found in the source, the system could fall
back to looking for the extracted *value* instead. This accepts two more documents.

I rejected it. A number like `604.80` appears in a total, a line item, and a
payment slip, and the fallback cannot tell which one the model meant. It buys
acceptance by giving up the guarantee the project exists to make. The code path
remains in the repository, off by default and covered by tests, because the
experiment is part of the evidence.

## Trade-offs

**A database job table instead of Redis and Celery.** A claim-and-lease poller in
Postgres demonstrates identical recovery semantics — crash mid-write, restart,
resume, no duplicate — with no broker and no second service to operate. Celery is
more recognisable; it is not more evidential. It also means the whole system runs
in one process on a free tier, which is how the demo is deployed.

**SQLite in week 1, Postgres from week 4.** Setting up a database was not allowed
to block the vertical slice. Nothing in the data access layer assumes SQLite
beyond connection pooling.

**The destination is a mock, but a shared one.** It stores records in a table with
a unique idempotency key, so its deduplication is visible to every process rather
than to one process's memory. Two independent guards hold: ours on `crm_write`,
the destination's on `crm_record`. A real CRM would deduplicate server-side in
exactly this shape. What is still missing is a real connector's authentication and
reconciliation.

**A stub reviewer identity.** Approval records who granted it, but there is no
authentication. That is a deliberate scope boundary, not an oversight.

**`schema_version` is recorded on every extraction, and the database schema is
migrated by Alembic.** What is still missing is a policy for what to do with
extractions written under an older contract version — re-extract, or read them
through a compatibility shim. That is a product decision, not a technical gap.

## What I would not claim

This is not production-ready, and the repository does not say it is. The documents
are synthetic and share an author with the rules, so accuracy here describes the
difficulty of this set, not live performance. The held-out result is real and
narrow. A replayed evaluation measures the validation, approval, and write layers;
only a live run measures the model.

## The next paid extension

In rough order of what a buyer would feel first:

1. **A second document type** — purchase orders or delivery notes — behind the same
   contract, to show the boundary holds under a schema change.
2. **A real destination connector** with authentication, server-side idempotency,
   and reconciliation against what the destination reports.
3. **Authentication and per-reviewer authorisation**, so approval means a named
   person with a role rather than a recorded string.
4. **OCR intake** for scanned PDFs, which is where evidence spans get genuinely
   hard and the quote-location approach would need reworking.
5. **Live evaluation against real documents** under a data agreement, replacing the
   assumed reviewer minutes with observed ones.

## Running it

```bash
pip install -e ".[dev]"
pytest                           # 180 tests, no API key
python scripts/demo.py           # extraction with evidence
python scripts/demo_approval.py  # approval, idempotent write, twenty replays
python scripts/demo_recovery.py  # 503, worker death mid-write, recovery
python evals/run.py              # regenerates evals/report.md
docker compose up                # API, worker, Postgres; review screen on :8000/review
```
