# Recovery runbook

What to do when a document does not reach the destination. Every question below
is answerable from two tables: `job` and `event`.

## First five minutes

1. `GET /jobs/review` — permanently failed and retry-exhausted jobs. If the
   document is here, the queue is working and something about this document is
   not.
2. `GET /documents/{id}` — status, the latest extraction, validation results,
   the approval, and the full event trail.
3. Check the document's status against what you expect:

   | Status | Means | Next |
   |---|---|---|
   | `received` | no extraction has run | is an extract job queued? |
   | `extraction_failed` | the provider call or its output failed | read `extraction.error_code` |
   | `extracted` | extracted, not yet validated | a validation step was interrupted |
   | `needs_review` | a business rule blocked it | read `validation_result`; this is a person's decision, not a bug |
   | `validated` | waiting for a human | nothing to fix |
   | `approved` | approved, write not settled | look at the write job |
   | `written` | done | nothing to do |

The event trail is append-only, so the history is intact even for a job that
crashed. Nothing recovers by deleting rows.

## Error classification

Retry policy is decided by type, never by string matching.

| Error | Code | Class | Behaviour |
|---|---|---|---|
| Provider timeout | `provider_timeout` | transient | retried with doubling backoff, up to `max_attempts` |
| Destination unavailable | `crm_unavailable` | transient | retried with doubling backoff |
| Provider refusal | `provider_refusal` | permanent | straight to review, one attempt |
| Malformed or schema-invalid output | `malformed_provider_output` | permanent | straight to review, one attempt |
| Destination rejection | `crm_rejected` | permanent | straight to review, one attempt |
| Approval missing, expired, or superseded | `approval_*` | permanent | straight to review, one attempt |
| Anything unrecognised | — | permanent | straight to review |

An unclassified error is treated as permanent on purpose. Retrying something
nobody has reasoned about is how a single failure becomes a storm.

A job that exhausted its retries is recorded as `transient_exhausted`, not
`permanent`. The distinction matters: the first usually means the dependency was
down for longer than the budget, the second means this document will never
succeed unchanged.

## Replaying a job

Replaying is always safe for a write. The idempotency key is derived from the
document id and the approved payload hash, the key column is `UNIQUE`, and the
destination deduplicates on the same key. A write that already succeeded returns
the existing record without calling the destination.

To replay a failed job, set it back to pending and let a worker pick it up:

```sql
UPDATE job
   SET status = 'pending', run_at = now(), lease_expires_at = NULL, locked_by = NULL
 WHERE id = '<job id>';
```

Do not reset `attempts`. The count is evidence, and week 5 reports it as part of
cost per accepted outcome.

## An interrupted worker

A worker claims a job by taking a lease. If the process dies, the lease expires
and the next worker reclaims the job — no operator action is needed. Reclaim
increments the attempt count, which is correct: the work was genuinely attempted.

A live lease is never stolen. If a job is stuck in `running` with a lease in the
future and you know the worker is gone, expire it:

```sql
UPDATE job SET lease_expires_at = now() WHERE id = '<job id>' AND status = 'running';
```

Recovery is safe because the destination write is idempotent. A worker that died
after calling the destination but before recording success will, on retry, find
the record already there and settle without creating a second one.

## What never to do

- **Never delete an event row.** The trail is the audit record and the evaluation
  input.
- **Never edit `extraction.draft` by hand.** Corrections go through a new
  extraction, which clears the approved payload hash and forces re-approval.
- **Never reset `attempts` to make a dashboard look better.**
- **Never raise `max_attempts` to push a permanent failure through.** A permanent
  failure will fail identically on attempt fifty.

## Verifying recovery

```bash
python scripts/demo_recovery.py
```

Drives the whole path: a 503 from the destination classified as transient and
retried, a worker killed mid-write, a fresh worker reclaiming the expired lease,
one destination record at the end, and an audit trail with both the failed and
the successful write attempt still in it.
