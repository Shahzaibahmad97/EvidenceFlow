from __future__ import annotations

from decimal import Decimal

from evals.cost import CostModel

COSTS = CostModel()


def test_model_cost_is_priced_per_million_tokens():
    assert COSTS.model_cost(1_000_000, 0) == Decimal("2.50")
    assert COSTS.model_cost(0, 1_000_000) == Decimal("10.00")


def test_reviewer_cost_is_priced_per_flagged_document():
    assert COSTS.reviewer_cost(15) == Decimal("35.00")
    assert COSTS.reviewer_cost(0) == Decimal("0")


def test_reviewer_time_dominates_at_realistic_volumes():
    tokens = COSTS.model_cost(100_000, 200_000)

    assert COSTS.reviewer_cost(1) > tokens


def test_assumptions_are_stated():
    assert len(COSTS.describe()) == 4
