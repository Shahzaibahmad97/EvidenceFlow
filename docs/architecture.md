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
