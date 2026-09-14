"""Cost assumptions. Every number here is a stated assumption, not a measurement."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CostModel:
    input_per_million: Decimal = Decimal("2.50")
    output_per_million: Decimal = Decimal("10.00")
    reviewer_rate_per_hour: Decimal = Decimal("35.00")
    review_minutes_per_document: Decimal = Decimal("4")

    def model_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) * self.input_per_million
            + Decimal(output_tokens) * self.output_per_million
        ) / Decimal(1_000_000)

    def reviewer_cost(self, documents_reviewed: int) -> Decimal:
        minutes = Decimal(documents_reviewed) * self.review_minutes_per_document
        return minutes / Decimal(60) * self.reviewer_rate_per_hour

    def describe(self) -> list[str]:
        return [
            f"model input ${self.input_per_million} per million tokens",
            f"model output ${self.output_per_million} per million tokens",
            f"reviewer ${self.reviewer_rate_per_hour} per hour",
            f"{self.review_minutes_per_document} minutes of review per flagged document",
        ]
