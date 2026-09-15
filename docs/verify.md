# Verify it yourself

Fifteen minutes, no API key, no account. Every check below is something a buyer
would reasonably ask you to prove.

## Start it

Either path works. Both seed thirty synthetic documents and process them.

**Containers** — API, worker and PostgreSQL as separate services:

```bash
docker compose up --build
```

**Deployed instance** — if one is running, open its URL and skip to check 1.
Everything below works there except the container commands in check 7.

**Without containers** — one process, SQLite:

```bash
pip install -e ".[dev]"
EVIDENCEFLOW_SEED_ON_START=true EVIDENCEFLOW_RUN_WORKER=true \
  uvicorn app.api.app:create_app --factory
```

Open <http://localhost:8000> — it lands on the review queue. You should see
thirty documents:
**15 validated, 13 needs review, 2 extraction failed.**

Run the automated pass first if you want the short version:

```bash
python scripts/e2e_live.py --base-url http://localhost:8000
```

61 checks, and it prints which document it used for each one. It makes more than
sixty writes a minute, so against a deployment left at the default rate limit it
will stop and tell you to raise `EVIDENCEFLOW_RATE_LIMIT_PER_MINUTE`. The default
is meant for a public URL, not for a test run.

---

## 1. Evidence is located, not asserted

Open any **validated** document, for example `inv_001_acme.txt`.

- The source on the left has seven highlighted spans.
- Hover one: the tooltip names the field it supports.
- Each highlight is a span the application found by searching the source for the
  model's quote. The model never says where a value is.

**What to look for:** the highlighted text is exactly the text the evidence panel
quotes. Nothing is highlighted that the panel does not claim.

## 2. Valid JSON is not a valid business outcome

Open `adv_document_discount.txt`.

- Every field is present and well-formed.
- Validation shows `line_items_sum_to_subtotal` failing: the captured lines sum to
  1200.00 against a subtotal of 1140.00, because the settlement discount is
  printed below the line items.
- **The approve button is disabled.**

Then open `adv_ambiguous_date.txt` — `03/04/2026` could be 3 April or 4 March, and
nothing in the document settles it. Routed to review, not guessed.

And `adv_unsupported_currency.txt` — extracted perfectly, in CHF, refused. Correct
extraction is not authorisation to write.

## 3. Approval is bound to the version you read

Open a **validated** document and approve it.

- The status becomes `approved` and the event trail records who approved it.

Now prove a stale page cannot approve. In one tab, open a validated document. In
another, re-run extraction for it:

```bash
curl -X POST http://localhost:8000/documents/<id>/extract
```

Go back to the first tab and press **Approve this version**. You get
*"The document changed since this page was loaded."* The approval carries the hash
of the payload the page was rendered with.

## 4. A replay creates no second record

On an approved document, press **Write to CRM**. You get `Wrote CRM-…`.

Press it again. You get `Already written as CRM-…` — the same record.

By API, twenty times:

```bash
for i in $(seq 20); do
  curl -s -X POST http://localhost:8000/documents/<id>/write \
    | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["external_id"], r["called_destination"])'
done
```

One `True`, nineteen `False`, one external id throughout.

## 5. A correction invalidates an approval

Approve a document, then re-extract it:

```bash
curl -X POST http://localhost:8000/documents/<id>/extract
curl -X POST http://localhost:8000/documents/<id>/write
```

The write is refused with `approval_missing`. Approval is bound to a payload hash,
and a new extraction clears it. Nobody has to remember to revoke anything.

## 6. The same invoice twice

`inv_001_acme.txt` and `adv_duplicate_number.txt` are the same invoice number from
the same supplier. On a fresh start **both are validated** — an uncommitted copy
claims nothing.

Approve and write `inv_001_acme.txt`. Now try to approve `adv_duplicate_number.txt`.

It is refused with `invoice_number_not_duplicate`, and the document moves to
`needs_review`. Approval re-validates at the moment of the decision, because
validation at intake is a snapshot and the world moved.

## 7. It survives losing the worker

With the container stack running:

```bash
# approve a validated document, then:
docker compose stop worker
curl -X POST http://localhost:8000/documents/<id>/jobs \
     -H 'Content-Type: application/json' -d '{"type":"write"}'
curl http://localhost:8000/jobs/<job id>          # pending, nothing is draining it
docker compose start worker
curl http://localhost:8000/documents/<id>         # written
```

The job survives the process. Check the event trail on the document: every attempt
is still there, including any that failed.

For the harder version — a worker that dies *mid-write* — run:

```bash
python scripts/demo_recovery.py
```

A 503 from the destination classified as transient and retried, a worker killed
holding the job, the lease expiring, another worker finishing the work. **Two
destination calls, one record.**

## 8. Nothing reached the destination that should not have

```bash
curl -s http://localhost:8000/documents | python3 -m json.tool | grep -c '"status": "written"'
```

Compare with the destination's own records:

```bash
# containers
docker compose exec db psql -U evidenceflow -tAc \
  "select count(*), count(distinct business_key) from crm_record"
```

The counts match, and `business_key` is unique — the destination itself refuses a
second record for one supplier and invoice number, independently of anything the
application believes.

## 9. The numbers

```bash
python evals/run.py && cat evals/report.md
```

Thirty documents, ten held out and never used to tune a rule or the prompt. Check:

- `Duplicate destination records: 0`
- `Causal label matched the hand-written label: 30/30`
- Twelve of the blocked documents are `postcondition` failures — the model was
  right and the answer was still no.
- Cost per accepted record, with reviewer time as 99% of it.

Also read the section titled *Attempted improvement* — an improvement that raised
acceptance and was rejected on principle.

## What you will not find

- No API key is needed and none is used. The `fake` provider replays committed
  fixtures, so a public deployment cannot spend money.
- No real documents. Everything is synthetic.
- No claim that this is production-ready. The evaluation says what it measures and
  what it does not.
