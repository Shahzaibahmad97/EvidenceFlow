# Three-minute demo script

Run `docker compose up` beforehand, or `EVIDENCEFLOW_SEED_ON_START=true
EVIDENCEFLOW_RUN_WORKER=true uvicorn app.api.app:create_app --factory`. Open
`/review`. Have a terminal ready in a second window.

Narration is what to say, not what to read out. Times are cumulative.

---

**0:00 — The claim (spoken over the review queue)**

"This is an invoice intake workbench. A model reads the document, and ordinary
code decides what may be done with what it read. Thirty synthetic invoices are
loaded. Notice that only some are green."

**0:20 — A normal document**

Open `inv_001_acme.txt`.

"Here is the straightforward case. The model proposed these fields. Every
highlight in the source on the left is a span the application located itself —
the model returned a quote, and we found that quote in the document. It does not
get to tell us where the number is."

Point at the validation panel. "Eleven rules ran, no model involved. Totals add
up, the currency is supported, the invoice number has not been seen before."

**0:50 — Approval and the write**

Click **Approve this version**, then **Write to CRM**.

"Approval is bound to a hash of exactly this payload. The write key is derived on
the server from the document id and that hash."

Click **Write to CRM** again. "Replayed. Same record, no second write. That is a
unique constraint and a destination that deduplicates on the same key, not a flag
somebody remembered to check."

**1:20 — A document that should not go through**

Open `adv_document_discount.txt`.

"Schema-valid. Well-formed JSON, every field present. And it is wrong: the
settlement discount is printed below the line items, so the captured lines sum to
1200 against a subtotal of 1140. A rule caught it and the approve button is
disabled. Valid JSON is not a valid business outcome."

Open `adv_duplicate_number.txt`. "This one is extracted perfectly and is a second
copy of an invoice we already have. Correct extraction is not authorisation to
write."

**2:00 — Failure and recovery**

Switch to the terminal, run `python scripts/demo_recovery.py`.

"The destination returns a 503. That is classified transient and retried. Then a
worker claims the job and dies mid-write. Its lease expires, another worker picks
it up, and the work completes — one destination record, and both the failed and
the successful attempt still in the audit trail. Nothing was lost and nothing was
duplicated."

**2:30 — The numbers**

Show `evals/report.md`.

"Thirty documents, ten held out and never used to tune anything. Zero duplicate
writes. Seventeen refused. Twelve of those seventeen are postcondition failures —
the model was right and the answer was still no. No prompt change fixes those."

Point at the cost table. "Cost per accepted record is three dollars, and reviewer
time is ninety-nine per cent of it. If I quoted you the token cost it would be
half a cent and it would be useless."

**2:50 — Close**

"Everything here is synthetic, and the tests run with no API key. The next
interesting question is not a better model — it is a second document type through
the same boundary."

---

## Recording notes

- Record the terminal and the browser separately and cut between them; do not
  screen-share a window that shows an API key field, even an empty one.
- `python scripts/demo_recovery.py` completes in under a second. Slow the clip or
  narrate over a still of the output.
- Three failure modes must appear: one normal document, one invalid document, one
  safe retry. That is the exit test for this week.
