from __future__ import annotations

import json
import time
from typing import Any

from app.domain.schema import InvoiceDraft
from app.providers.base import (
    MalformedProviderOutput,
    ProviderRefusal,
    ProviderResult,
    ProviderTimeout,
)
from app.providers.prompt import EXTRACTION_PROMPT, PROMPT_HASH


def _strict_schema() -> dict[str, Any]:
    schema = InvoiceDraft.model_json_schema()
    _tighten(schema)
    return schema


def _tighten(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("title", None)
        if node.get("type") == "object":
            node["additionalProperties"] = False
            if "properties" in node:
                node["required"] = list(node["properties"])
        for value in node.values():
            _tighten(value)
    elif isinstance(node, list):
        for item in node:
            _tighten(item)


class OpenAIProvider:
    def __init__(self, client: Any, model: str, timeout_seconds: float = 60.0) -> None:
        self._client = client
        self._model = model
        self._timeout = timeout_seconds

    def extract(self, document_text: str) -> ProviderResult:
        started = time.perf_counter()
        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=EXTRACTION_PROMPT,
                input=document_text,
                timeout=self._timeout,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "invoice_draft",
                        "strict": True,
                        "schema": _strict_schema(),
                    }
                },
            )
        except Exception as exc:
            if _is_timeout(exc):
                raise ProviderTimeout(str(exc)) from exc
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)

        refusal = _refusal_text(response)
        if refusal:
            raise ProviderRefusal(refusal)

        text = getattr(response, "output_text", None)
        if not text:
            raise MalformedProviderOutput("provider returned no output text")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MalformedProviderOutput(f"output was not JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise MalformedProviderOutput("output JSON was not an object")

        usage = getattr(response, "usage", None)
        return ProviderResult(
            raw=raw,
            model=getattr(response, "model", self._model),
            prompt_hash=PROMPT_HASH,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            request_id=getattr(response, "id", None),
        )


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return type(exc).__name__ in {"APITimeoutError", "Timeout", "ReadTimeout"}


def _refusal_text(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return getattr(part, "refusal", "refused")
    return None
