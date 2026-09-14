from __future__ import annotations

import hashlib

EXTRACTION_PROMPT = """\
You extract structured data from an invoice. Return only the fields defined by the
response schema.

For every evidenced field, `quote` must be a verbatim substring of the invoice text
that supports `value`. Copy it exactly as it appears, including punctuation. Do not
paraphrase, reformat, or assemble a quote from separate parts of the document. If you
cannot find supporting text for a field, you must still quote the closest passage you
relied on.

Amounts are strings with a decimal point and no thousands separators or currency
symbols. `issue_date` is an ISO date, YYYY-MM-DD. `currency` is a three-letter
ISO 4217 code.
"""

PROMPT_HASH = hashlib.sha256(EXTRACTION_PROMPT.encode()).hexdigest()[:16]
