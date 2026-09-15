---
title: EvidenceFlow
emoji: 📄
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: AI invoice intake with evidence, approval and replay protection
---

# EvidenceFlow

An AI document intake and approval workbench. A model proposes structured data
from an invoice; ordinary code decides what may be done with it.

Open **[/review](/review)** for the queue. Thirty synthetic invoices are seeded:
15 validated, 13 needing review, 2 refused at the schema boundary.

Things worth trying:

- **`inv_001_acme.txt`** — every highlighted span was located by searching the
  source for the model's quote. The model never says where a value is.
- **`adv_document_discount.txt`** — perfect JSON, and refused: a settlement
  discount below the line items makes the captured lines sum to 1200.00 against a
  1140.00 subtotal. The approve button is disabled.
- **Approve a validated document, write it, then press write again.** The same
  record comes back. The key is derived from the document and the approved payload
  hash, the column is unique, and the destination deduplicates on it too.
- **`adv_duplicate_number.txt`** — the same invoice as `inv_001_acme.txt`. Write
  the original first, then try to approve this one.

No model is called here. This Space runs the deterministic fixture provider, so
it holds no API key and cannot spend one. All documents are synthetic.

Source, evaluation and case study: <https://github.com/Shahzaibahmad97/EvidenceFlow>
