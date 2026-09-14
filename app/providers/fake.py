from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from app.providers.base import ProviderError, ProviderResult
from app.providers.prompt import PROMPT_HASH

Handler = Callable[[str], dict[str, Any]]

FAKE_MODEL = "fake-extractor-1"
CHARACTERS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(len(text) // CHARACTERS_PER_TOKEN, 1)


class FakeProvider:
    def __init__(self, handler: Handler, *, latency_ms: int = 0) -> None:
        self._handler = handler
        self._latency_ms = latency_ms
        self.calls: list[str] = []

    def extract(self, document_text: str) -> ProviderResult:
        self.calls.append(document_text)
        raw = self._handler(document_text)
        return ProviderResult(
            raw=raw,
            model=FAKE_MODEL,
            prompt_hash=PROMPT_HASH,
            latency_ms=self._latency_ms,
            input_tokens=_estimate_tokens(document_text),
            output_tokens=_estimate_tokens(json.dumps(raw)),
            request_id=f"fake-{len(self.calls)}",
        )

    @classmethod
    def returning(cls, payload: dict[str, Any], **kwargs: Any) -> "FakeProvider":
        return cls(lambda _: payload, **kwargs)

    @classmethod
    def raising(cls, error: ProviderError, **kwargs: Any) -> "FakeProvider":
        def handler(_: str) -> dict[str, Any]:
            raise error

        return cls(handler, **kwargs)

    @classmethod
    def from_mapping(cls, payloads: Mapping[str, dict[str, Any]], **kwargs: Any) -> "FakeProvider":
        def handler(text: str) -> dict[str, Any]:
            try:
                return payloads[text]
            except KeyError:
                raise ProviderError(f"no fake payload for document of {len(text)} chars")

        return cls(handler, **kwargs)

    @classmethod
    def from_fixtures(cls, *directories: Path, **kwargs: Any) -> "FakeProvider":
        payloads = {
            path.read_text(): json.loads(path.with_suffix(".json").read_text())
            for directory in directories
            for path in sorted(directory.glob("*.txt"))
            if path.with_suffix(".json").exists()
        }
        return cls.from_mapping(payloads, **kwargs)
