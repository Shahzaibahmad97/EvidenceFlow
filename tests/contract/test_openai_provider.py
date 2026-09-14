from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.providers.base import MalformedProviderOutput, ProviderRefusal, ProviderTimeout
from app.providers.openai_provider import OpenAIProvider, _strict_schema

MODEL = "gpt-4.1-2025-04-14"


class StubResponses:
    def __init__(self, result) -> None:
        self._result = result
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _client(result):
    return SimpleNamespace(responses=StubResponses(result))


def _response(**kwargs):
    return SimpleNamespace(
        output_text=kwargs.pop("output_text", "{}"),
        output=kwargs.pop("output", []),
        model=MODEL,
        id="resp_1",
        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
        **kwargs,
    )


def test_schema_is_closed_and_fully_required():
    schema = _strict_schema()

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(schema)
    assert set(schema["properties"]) >= {"invoice_number", "total", "line_items"}


def test_money_and_dates_are_strings_in_the_wire_schema():
    definitions = _strict_schema()["$defs"]
    line_item = definitions["LineItem"]["properties"]

    assert line_item["amount"] == {"type": "string"}
    date_field = next(
        value for key, value in definitions.items() if "date" in key
    )["properties"]["value"]
    assert date_field == {"type": "string"}


def test_successful_call_carries_provider_metadata(fixtures):
    payload = fixtures.payload("inv_001_acme")
    client = _client(_response(output_text=__import__("json").dumps(payload)))

    result = OpenAIProvider(client, MODEL).extract("invoice text")

    assert result.raw == payload
    assert result.model == MODEL
    assert (result.input_tokens, result.output_tokens) == (100, 200)
    assert client.responses.kwargs["text"]["format"]["strict"] is True
    assert client.responses.kwargs["model"] == MODEL


def test_timeout_is_classified():
    with pytest.raises(ProviderTimeout):
        OpenAIProvider(_client(TimeoutError("read timeout")), MODEL).extract("text")


def test_non_json_output_is_malformed():
    with pytest.raises(MalformedProviderOutput):
        OpenAIProvider(_client(_response(output_text="not json")), MODEL).extract("text")


def test_empty_output_is_malformed():
    with pytest.raises(MalformedProviderOutput):
        OpenAIProvider(_client(_response(output_text="")), MODEL).extract("text")


def test_refusal_is_classified():
    refusal = SimpleNamespace(
        content=[SimpleNamespace(type="refusal", refusal="cannot comply")]
    )
    client = _client(_response(output=[refusal]))

    with pytest.raises(ProviderRefusal, match="cannot comply"):
        OpenAIProvider(client, MODEL).extract("text")
