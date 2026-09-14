from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Generic, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    WithJsonSchema,
)

SCHEMA_VERSION = "1.0.0"

T = TypeVar("T")


def _to_decimal(v: object) -> object:
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str):
        cleaned = v.strip().replace(",", "").replace(" ", "")
        try:
            return Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal amount: {v!r}") from exc
    return v


def _to_date(v: object) -> object:
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        return date.fromisoformat(v.strip())
    return v


# Money and dates travel as strings so the provider JSON schema stays within the
# keyword set strict structured outputs accepts, and so no amount passes through
# a float.
Money = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
    WithJsonSchema({"type": "string"}),
]

IsoDate = Annotated[
    date,
    BeforeValidator(_to_date),
    PlainSerializer(lambda d: d.isoformat(), return_type=str),
    WithJsonSchema({"type": "string"}),
]

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class EvidencedField(BaseModel, Generic[T]):
    """A proposed value plus the verbatim source text the model claims supports it."""

    value: T
    quote: str = Field(min_length=1)


class LineItem(BaseModel):
    description: str
    quantity: Money
    unit_price: Money
    amount: Money


class InvoiceDraft(BaseModel):
    invoice_number: EvidencedField[str]
    supplier: EvidencedField[str]
    currency: EvidencedField[CurrencyCode]
    issue_date: EvidencedField[IsoDate]
    line_items: list[LineItem]
    subtotal: EvidencedField[Money]
    tax: EvidencedField[Money]
    total: EvidencedField[Money]

    def evidenced_fields(self) -> dict[str, EvidencedField]:
        return {
            name: value
            for name, value in self
            if isinstance(value, EvidencedField)
        }

    def payload_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
