# EvidenceFlow — build plan (v2, reshaped)

Window: 14 September – 25 October 2026. Budget: ~6 focused hours per week.

One capability, end to end:

```
synthetic invoice -> typed extraction (with evidence) -> deterministic validation
  -> evidence review -> version-bound approval -> idempotent mock-CRM write
```

The model proposes a structured draft. Ordinary code owns arithmetic, required
fields, workflow state, authorization, approval, idempotency, and audit history.

Synthetic data only. One document type, one provider, one mock destination.

---

## Standing rules

These hold for every week. Violating one is a defect regardless of which week's
work introduced it.

1. **Model output is never written to a business record.** It lands in an
   `extraction` row and is promoted only by validated, approved transitions.
2. **Deterministic tests must pass with no API key.** The fake provider is the
   default in CI. Live provider calls run only under an opt-in command.
3. **Every state change appends an event.** No silent mutation. The event log is
   the audit trail and the eval trajectory — the same table serves both.
4. **Evidence is verified, not trusted.** See "Evidence contract" below.
5. **Idempotency and approval binding are enforced by database constraints**, not
   by read-then-write application logic.
6. **No secrets, no real documents, in the repository.** `.env.example` only.
7. Each commit leaves `pytest` green.

## Evidence contract

The model does **not** emit character offsets — it is unreliable at them, and an
unverifiable offset is not evidence. Instead:

- For each evidenced field the model returns `quote`: a verbatim substring of the
  source document that supports the value.
- Application code locates `quote` in the source text. Exact match resolves to a
  `(start, end)` span and a line number, computed by us.
- If the quote is not found verbatim, the evidence is **rejected**: the field is
  marked `evidence_unverified` and the document cannot reach approval on the
  strength of that field.

This makes provenance checkable by ordinary code, which is the point of the
project. Normalize only whitespace before matching; never fuzzy-match.

## Cost per accepted outcome

Defined once, used everywhere:

```
cost_per_accepted = (model_cost + retry_cost + reviewer_minutes * REVIEWER_RATE)
                    / accepted_records
```

`REVIEWER_RATE` is a stated configuration assumption, surfaced in the report.
Reporting token cost alone is the failure this metric exists to prevent.

---

## Week 1 — 14–20 Sep: typed extraction contract, evidence, event log

Evidence and the event log are in the contract from the first commit. Retrofitting
either means rewriting the schema, the prompt, and the storage layer.

**Build**

- `app/domain/schema.py`: `InvoiceDraft` (Pydantic) — `invoice_number`, `supplier`,
  `currency`, `issue_date`, `line_items[]`, `subtotal`, `tax`, `total`, plus
  `EvidencedField[T]` wrapping `value` and `quote`. Explicit `SCHEMA_VERSION`.
- `app/providers/base.py`: `ExtractionProvider` protocol — one method, takes
  document text, returns a raw payload plus call metadata (model id, latency,
  token usage, request id).
- `app/providers/fake.py`: deterministic provider driven by fixture files.
  Supports injected failure modes: timeout, malformed JSON, schema-invalid
  payload, refusal.
- `app/providers/openai_provider.py`: OpenAI Responses API with Structured
  Outputs. Pin an exact model snapshot id in config — never a floating alias.
- `app/domain/evidence.py`: quote resolution and verification per the contract above.
- `app/repositories/`: SQLAlchemy models — `document`, `extraction`, `event`.
  `extraction` stores raw provider payload, parsed draft, schema version, model id,
  prompt hash, latency, usage, and a `payload_hash` over the parsed draft.
- `app/api/`: `POST /documents` (store synthetic text), `POST /documents/{id}/extract`,
  `GET /documents/{id}`.
- `tests/fixtures/invoices/`: 5 valid invoices + 3 failure cases.

**Event schema — settle it now**

```
event(id, document_id, extraction_id?, type, actor, payload_json, created_at)
```

`type` ∈ `extraction_requested`, `extraction_succeeded`, `extraction_failed`,
`evidence_verified`, `evidence_rejected`, `validation_completed`, `correction_applied`,
`approval_granted`, `write_attempted`, `write_succeeded`, `write_failed`.
Append-only: no updates, no deletes, ever.

**Test**

Happy path; missing required field; unsupported currency; malformed provider output;
provider timeout; provider refusal; quote not present in source → evidence rejected;
extraction row created even when extraction fails.

**Visible artefact** — public repo, 60–90s terminal/API demo, architecture sketch,
sample input/output, test command in the README.

**Exit test** — a fresh clone runs the full deterministic suite with no API key. One
configured key runs the five live examples. Every extracted field either carries a
resolved span or is marked unverified.

---

## Week 2 — 21–27 Sep: deterministic validation + adversarial dataset

**Build**

- `app/domain/validation.py`: pure functions, no model, no I/O. Required fields;
  line-item arithmetic; `subtotal + tax == total` within a stated tolerance;
  supported-currency allowlist; issue date plausible and unambiguous; duplicate
  `invoice_number` per supplier.
- Validation results stored in their own table, never merged into the extraction
  payload. Each result: rule id, outcome (`pass`/`fail`/`needs_review`), message.
- Status routing: `extracted -> validated | needs_review`. Any failed blocking rule
  or unverified evidence on a consequential field routes to `needs_review`.

**Dataset — 20 documents, ground truth written by hand**

Model-generated fixtures with model-generated labels score ~100% and prove nothing.
Hand-label. Include deliberately hard cases:

- ambiguous date (`03/04/2026`), so DD/MM vs MM/DD must be resolved or flagged
- line discount, and a document-level discount
- per-line tax vs. document-level tax
- rounding drift of one minor unit
- subtotal on a later page than the line items
- mixed currency symbol and ISO code disagreeing
- missing invoice number
- near-duplicate of an existing invoice number
- credit note (negative total)
- schema-valid but semantically wrong: totals that parse cleanly but do not add up

**Visible artefact** — `evals/report-v1.md`: field-level results across the 20,
worked examples of schema-valid semantic failures, and the LinkedIn post
"Valid JSON is not a valid business outcome."

**Exit test** — every accepted field traces to a verified source span; each known
business-rule failure in the dataset is provably unable to reach approval.

---

## Week 3 — 28 Sep–4 Oct: approval-gated, idempotent write

The strongest week. Do not compress it.

**Build**

- `approve_extraction(document_id, extraction_id, actor)` — permitted only from
  `validated`. Records `payload_hash` of the approved extraction, the actor, and an
  expiry.
- Approval binds to the **content hash**, not a version counter. A correction
  produces a new extraction and a new hash, which invalidates the prior approval by
  construction.
- `create_mock_record` — server-derived idempotency key
  `sha256(document_id + payload_hash)`. Never client-supplied.
- Uniqueness enforced by a DB `UNIQUE` constraint on `crm_write.idempotency_key`.
  The mock CRM **also** dedupes on the key, so replay safety is proven end to end
  rather than only on our side.
- The write transition is a single guarded update:
  `UPDATE document SET status='written' WHERE id=? AND status='approved' AND approved_payload_hash=?`
  — zero rows affected means reject, no write. No read-then-write anywhere.
- A stub actor identity is enough, but approval must record *who*.

**Test**

Write without approval; approval for a different document; approval then correction
then write; double-click (two concurrent approvals); repeated API delivery ×20;
expired approval; concurrent writes racing on the same key.

**Visible artefact** — 2-minute demo: one clean approval, one blocked stale approval,
one replay creating no duplicate.

**Exit test** — no mock-CRM record exists without a matching current approval; twenty
replays produce exactly one record; the guarantee survives concurrency, not just
sequential calls.

---

## Week 4 — 5–11 Oct: durable workflow state and recovery

**Decision: a database-backed job table, not Redis + Celery.** A claim-and-lease
poller in Postgres demonstrates identical recovery semantics — crash mid-write,
restart, resume, no duplicate — with a fraction of the setup cost and a far easier
demo to narrate. Celery is only more *recognizable*; it is not more *evidential*.
Swap it in at the end of the week only if the week has slack.

**Build**

- `job(id, type, payload, status, attempts, lease_expires_at, last_error, created_at)`.
- Claim with `SELECT ... FOR UPDATE SKIP LOCKED` and a lease; an expired lease is
  reclaimable, which is what makes crash recovery work.
- Extraction and CRM write both run as jobs.
- Retry classification: transient (timeout, 5xx, connection reset) retries with
  capped exponential backoff; permanent (4xx, schema-invalid, business-rule failure)
  goes straight to the review queue. Never retry a permanent error.
- Recovery is safe because the write is idempotent — re-running a claimed job cannot
  duplicate the destination record.

**Test**

Provider timeout; mock CRM 503 then success; worker killed mid-write; process
restart resumes the interrupted job; duplicate job delivery; permanent 4xx routes to
review without retry; lease expiry reclaim.

**Visible artefact** — failure-recovery demo plus `docs/runbook.md`: retryable vs.
terminal errors, how to replay, how to recover manually, what to check first.

**Exit test** — kill the worker mid-write, restart it, and the workflow completes with
no lost audit history and exactly one destination record.

---

## Week 5 — 12–18 Oct: causal evaluation and task economics

**Build**

- Dataset to 30 documents; 10 held out and never used during prompt development.
  Holdout discipline is the claim — respect it or the number is worthless.
- `evals/run.py` reconstructs each trajectory from the event log written since
  Week 1. No new instrumentation should be needed; if it is, Week 1 under-specified
  the event schema and that is the finding.
- Label the **earliest causal error** per failed trajectory:
  `selection` | `completeness` | `truthfulness` | `postcondition`.
  Label the root error, not the inherited damage downstream of it.
- Pin model snapshot id and prompt hash per run; results are otherwise not reproducible.

**Measure**

Field accuracy; document acceptance rate; reviewer correction rate; duplicate-write
count (must be 0); p50/p95 latency; tokens; retry count; cost per accepted record per
the formula above. Report routine and hard documents separately — a blended number
hides exactly what a buyer wants to see.

**Visible artefact** — reproducible report: baseline, one attempted improvement,
before/after, remaining failures stated plainly. No "production-ready" claim.

**Exit test** — one command regenerates the report from recorded fixtures; live runs
and replayed runs are distinguishable in the output.

---

## Week 6 — 19–25 Oct: buyer-facing release

**Build**

- Minimal server-rendered review screen: document text, extracted fields, each
  field's highlighted source span, validation results, approve button. The screen is
  a view over server state, never a source of truth; it revalidates the payload hash
  at click time.
- `docker-compose.yml`, `.env.example`, seed command for synthetic data, `/health`.
- GitHub Actions: deterministic suite, no API key. Live eval stays a separate opt-in
  command.
- Deploy only if cheap and safe; otherwise ship a reliable local demo. A local demo
  that works beats a deployment that costs money and breaks.

**Visible artefact** — 3-minute narrated demo and `docs/case-study.md`: buyer problem,
constraints, boundary design, failure tests, measured results, trade-offs, next paid
extension.

**Exit test** — a buyer grasps problem and evidence in five minutes; a developer runs
it from the README; the demo shows one normal document, one invalid document, one
safe retry.

---

## Acceptance contract

Complete only when all hold:

- 30 synthetic documents, 10 held out, ground truth hand-written.
- Schema validation and business validation are separate and separately stored.
- Every accepted record has verified, reviewable source evidence.
- No action occurs without an approval bound to the current payload hash.
- Duplicate delivery and repeated approval create no duplicate destination record,
  under concurrency.
- A worker restart recovers an interrupted workflow with audit history intact.
- The evaluation reports real results: accuracy, latency, usage, corrections,
  retries, and cost per accepted outcome including reviewer time.
- CI runs deterministic tests with no API key; live evaluation is opt-in.
- README, architecture note, runbook, demo, and case study are published.

## Branching

- `master` — released state. Only ever receives merges from `develop` (or a
  `hotfix/*` branch). Never committed to directly.
- `develop` — integration branch. Weekly work lands here.
- `feature/<short-name>` — one per unit of work, branched from `develop`, merged
  back into `develop`. Example: `feature/extraction-contract`.
- `hotfix/<short-name>` — branched from `master`, merged into both `master` and
  `develop`.

A week's exit test passing is what justifies a `develop` -> `master` merge. Tag
each release `v0.<week>.0`.

## Stack

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy, pytest. PostgreSQL for business and
audit state (SQLite acceptable in Week 1 only, if setup would otherwise block the
vertical slice). OpenAI Responses API with Structured Outputs behind
`ExtractionProvider`. Server-rendered HTML for review. Docker Compose, GitHub Actions.

Provider choice is a one-file change behind the adapter; the interface is the contract.

## Repository shape

```
evidenceflow/
  app/
    api/
    domain/          schema, evidence, validation, state transitions
    providers/       base, fake, openai
    workflows/       jobs, retry policy
    repositories/
  tests/
    fixtures/invoices/
    contract/
    integration/
    replay/
  evals/
    dataset.jsonl
    held_out.jsonl
    run.py
    report.md
  docs/
    PLAN.md
    architecture.md
    runbook.md
    case-study.md
  docker-compose.yml
  README.md
```

## Open items

- Retention / PII stance: trivial under synthetic data, but state it — buyers ask.
- Schema migration when `SCHEMA_VERSION` bumps mid-dataset: decide before Week 5.
- Approval actor identity is a stub; say so explicitly in the case study.

## Deliberately excluded from v1

OCR and scanned PDFs. Email intake. A real accounting or CRM connector. Multiple
document types or providers. Autonomous payment. Multi-agent orchestration. A
frontend framework.

## First session (two hours, time-boxed)

1. Repository and Python environment.
2. `InvoiceDraft` with `EvidencedField`, plus five synthetic fixtures — schema and
   fixtures before the prompt.
3. `ExtractionProvider` protocol and the fake provider.
4. Event table and append helper.
5. Extraction endpoint persisting an extraction attempt and its events.
6. Happy-path test, timeout test, invalid-output test.
7. Rough terminal recording. Observable behavior, not polish.
