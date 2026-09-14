from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.approval import ApprovalExpired
from app.domain.jobs import DEFAULT_BASE_BACKOFF, backoff, is_transient
from app.providers.base import MalformedProviderOutput, ProviderRefusal, ProviderTimeout
from app.providers.crm import CrmRejected, CrmUnavailable


@pytest.mark.parametrize(
    "error", [ProviderTimeout("read timeout"), CrmUnavailable("503 from destination")]
)
def test_transient_errors_are_retryable(error):
    assert is_transient(error)


@pytest.mark.parametrize(
    "error",
    [
        ProviderRefusal("declined"),
        MalformedProviderOutput("not json"),
        CrmRejected("422 unprocessable"),
        ApprovalExpired("expired"),
    ],
)
def test_permanent_errors_are_not_retried(error):
    assert not is_transient(error)


def test_an_unrecognised_error_is_treated_as_permanent():
    assert not is_transient(ValueError("something nobody classified"))


def test_backoff_doubles_per_attempt():
    assert backoff(1) == DEFAULT_BASE_BACKOFF
    assert backoff(2) == DEFAULT_BASE_BACKOFF * 2
    assert backoff(3) == DEFAULT_BASE_BACKOFF * 4
    assert backoff(1, timedelta(seconds=1)) == timedelta(seconds=1)


def test_backoff_never_goes_backwards_for_a_first_attempt():
    assert backoff(0) == DEFAULT_BASE_BACKOFF
