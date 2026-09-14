# Architecture

## Boundaries

```
  HTTP request
      |
  app/api            transport only: parse, dispatch, serialize
      |
  app/services       orchestration: call provider, verify evidence, append events
      |        \
      |         app/providers      the only code that talks to a model
      |
  app/domain         pure: schema, evidence resolution, vocabulary. No I/O.
      |
  app/repositories   persistence. Business rows and the append-only event log.
```

`app/domain` imports nothing from the layers above it. A provider is reachable
only through `ExtractionProvider`, so the OpenAI adapter and the fake provider are
interchangeable and the deterministic test suite never needs a network.

## What the model owns, and what it does not

The model owns exactly one thing: turning variable document text into a proposed
`InvoiceDraft`. It does not own arithmetic, required-field policy, currency
policy, workflow status, authorization, approval, idempotency, or audit history.

A provider response is persisted as an `extraction` row. It is never promoted into
a business record by the extraction path — promotion happens only through
validated, approved transitions, which arrive in weeks 2 and 3.

## The evidence contract

The model does not emit character offsets. It is unreliable at them, and an
offset nobody can check is not evidence.

Instead each evidenced field carries a `quote`: a verbatim substring of the source
document. `app/domain/evidence.py` locates that quote in the source and computes
the `(start, end, line)` span itself. Matching collapses whitespace runs — real
documents wrap and pad — but is never fuzzy: a paraphrase does not match.

A quote that cannot be located is rejected. The field is recorded as unverified,
and the document routes to `needs_review` rather than `extracted`. From week 3 an
unverified consequential field will also block approval.

The result is that provenance is checkable by ordinary code, which is the whole
argument of the project.

## Data model

| Table        | Holds                                                                    |
|--------------|--------------------------------------------------------------------------|
| `document`   | source text, filename, workflow status                                    |
| `extraction` | raw provider payload, parsed draft, evidence spans, `payload_hash`, model id, prompt hash, latency, token usage, request id, error code |
| `event`      | append-only trail: type, actor, payload, timestamp                        |

`payload_hash` is a SHA-256 over the canonical JSON of the parsed draft. It is
stable across key ordering and changes with any value. Week 3 binds approval to
this hash rather than to a version counter, so a correction invalidates a prior
approval by construction rather than by a check someone has to remember to write.

Extractions are never updated. Re-extracting appends a new row, so correction
history survives.

## The event log

One append-only table serves two purposes: it is the audit trail a reviewer reads,
and it is the trajectory the week 5 evaluation replays to label the earliest
causal error. Both consumers were designed for in week 1 — adding the log later
would have meant reconstructing history that was never recorded.

Types: `extraction_requested`, `extraction_succeeded`, `extraction_failed`,
`evidence_verified`, `evidence_rejected`, `validation_completed`,
`correction_applied`, `approval_granted`, `write_attempted`, `write_succeeded`,
`write_failed`.

Rows are inserted, never updated or deleted.

## Failure taxonomy

Provider failures carry a stable code, so retry policy (week 4) can classify
without string matching:

| Code                        | Cause                                        | Disposition        |
|-----------------------------|----------------------------------------------|--------------------|
| `provider_timeout`          | the call did not return in time              | transient, retry   |
| `provider_refusal`          | the model declined                           | permanent, review  |
| `malformed_provider_output` | not JSON, or JSON that fails the schema      | permanent, review  |

Every failure still writes an `extraction` row and an `extraction_failed` event. A
failed attempt is evidence too — dropping it would hide the cost of retries from
the week 5 economics.

## Storage

SQLite during week 1, by the plan's explicit allowance, so the vertical slice was
not blocked on database setup. PostgreSQL from week 4, where the durable job table
needs `SELECT ... FOR UPDATE SKIP LOCKED`. Nothing in the data access layer
assumes SQLite beyond connection pooling.

## Validation

`app/domain/validation.py` holds eleven rules. They are pure functions over a
`ValidationInput`: the parsed draft, the source text, the evidence results, the
supplier and invoice numbers already seen, and today's date. They call no model
and touch no database, so every rule is testable in isolation and the duplicate
check is supplied by the caller rather than reached for.

Each rule returns `pass`, `needs_review`, or `fail`:

| Outcome | Meaning | Example |
|---|---|---|
| `pass` | nothing to answer for | totals add up |
| `needs_review` | a person must decide | one minor unit of rounding drift, an ambiguous date, a currency symbol contradicting the code |
| `fail` | the record cannot be correct | line items do not sum to the subtotal, unsupported currency, redelivered invoice number |

Results are written to `validation_result`, never merged into the extraction
payload. The model's proposal and our verdict on it stay separately readable, so
a reviewer can see what was proposed and why it was refused.

Routing is a single decision point in `app/services/validation.py`: all rules
pass, or the document goes to `needs_review`. Extraction does not route — it
records what happened and leaves the verdict to the rules.

The distinction the rules exist to draw is between a draft that parses and a
draft that could be true. A settlement discount printed below the line items
yields a perfectly schema-valid draft whose lines sum to the wrong subtotal. A
correctly extracted invoice in an unsupported currency is not a licence to write.
A redelivered invoice with every field right is still a duplicate.

## Approval and the write gate

Approval binds to the extraction's `payload_hash`, not to a version counter. The
document carries `approved_payload_hash`, and a new extraction clears it, so a
correction invalidates a prior approval by construction rather than by a check
somebody has to remember to write.

`approve_extraction` refuses anything that is not currently `validated`, and
refuses an extraction that is no longer the document's latest. The approving
actor and an expiry are recorded on the approval row and in the event.

The destination write is guarded four ways, and each guard is structural:

1. **A server-derived key.** `idempotency_key(document_id, payload_hash)` is
   length-prefixed before hashing, so no combination of ids can collide by
   shifting the boundary between them. Clients never supply it.
2. **A database constraint.** `crm_write.idempotency_key` is `UNIQUE`. Two racing
   writers cannot both claim the same key, whatever the application does.
3. **A deduplicating destination.** `MockCrm` keys its records the same way, so
   even a duplicate call cannot produce a second record. Idempotency is proved
   end to end, not only on our side.
4. **A guarded transition.** The document moves to `written` with a single
   `UPDATE ... WHERE id = ? AND status = 'approved' AND approved_payload_hash = ?`.
   Zero rows affected means the document left the approved state while the write
   was in flight, and the write is rejected. There is no read-then-write anywhere
   in the path.

Replays are ordered before expiry checks. A write that already succeeded returns
the existing record as a no-op even if the approval has since expired — a retry
of settled work is not a new action and must not become an error.

A failed destination call leaves the `crm_write` row in `failed` with its attempt
count, and the document still `approved`. Retrying is safe because the key has
not changed and the destination dedupes.

## Durable workflow state

Extraction and destination writes run as rows in a `job` table. There is no
broker and no second service: a claim is a guarded `UPDATE`, and a lease is a
timestamp.

```
claim:   UPDATE job SET status='running', locked_by=?, lease_expires_at=?,
                        attempts = attempts + 1
          WHERE id = ? AND status IN ('pending','running')
            AND (lease_expires_at IS NULL OR lease_expires_at <= now)
```

Candidate rows are selected with `FOR UPDATE SKIP LOCKED` where the dialect
supports it, but that is an optimisation. Correctness comes from the guarded
update: two workers may select the same row, and only one will see `rowcount 1`.

A worker runs three separate transactions per job: claim, dispatch, settle. That
separation is the point. If claim and dispatch shared a transaction, a rollback
on failure would also roll back the attempt counter and — worse — discard the
extraction row and events the services had just recorded. `_dispatch` returns the
failure rather than raising, so the audit rows commit and only then is the job
marked failed.

A crashed worker needs no operator action. Its lease expires, the next claim
reclaims the row, and the attempt count increments because the work really was
attempted. Recovery is safe only because the destination write is idempotent: a
worker that died after calling the destination finds the record already there.

Retry classification is by exception type, never by string matching. Transient
errors (provider timeout, destination unavailable) retry with doubling backoff
until `max_attempts`; everything else, including anything unrecognised, goes to
the review queue on the first attempt. Exhausted retries and permanent failures
are recorded distinctly, because they mean different things to whoever is on
call.

The web process can host the worker in a background thread
(`EVIDENCEFLOW_RUN_WORKER=true`) or the worker can run separately. The job table
is the source of truth either way, which is what makes a free single-process
deployment behave identically to a two-service one.

## Evaluation

The evaluation replays documents through the real pipeline — worker, jobs,
extraction, validation, approval, write — rather than calling the services
directly. Retries, attempt counts and destination calls are therefore measured,
not asserted.

Trajectories are reconstructed from rows the application already writes: the
event log, `extraction`, `validation_result`, `crm_write` and `job`. Week 1 put
the event log in for this reason; no instrumentation was added for the report.

Each blocked document carries one label, the **earliest causal error**:

| Label | Meaning |
|---|---|
| `selection` | the model took the wrong value from the document |
| `completeness` | a required field was not there to take |
| `truthfulness` | the evidence offered does not appear in the source |
| `postcondition` | extraction was faithful; the record still cannot be written |

Labels are derived from a precedence table in `evals/labels.py`, not from the
order rules happen to be evaluated in. A document whose lines were mis-read and
whose totals then failed to add up is one selection error, not two failures. A
mis-signed credit note is a postcondition failure even though a sum rule fires
first, because the sum is the symptom.

Every document also carries a hand-written expected label. The harness compares
its derived label against the written one and fails CI on any mismatch, so the
taxonomy cannot drift quietly.

`--split held_out` runs only the ten documents held back. They were written after
the rules were fixed, and no rule, threshold or prompt was changed after seeing
their results.
