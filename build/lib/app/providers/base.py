from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(Exception):
    code = "provider_error"


class ProviderTimeout(ProviderError):
    code = "provider_timeout"


class ProviderRefusal(ProviderError):
    code = "provider_refusal"


class MalformedProviderOutput(ProviderError):
    code = "malformed_provider_output"


@dataclass(frozen=True)
class ProviderResult:
    raw: dict[str, Any]
    model: str
    prompt_hash: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None


class ExtractionProvider(Protocol):
    def extract(self, document_text: str) -> ProviderResult: ...
