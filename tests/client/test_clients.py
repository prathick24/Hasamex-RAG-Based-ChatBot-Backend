import json

import httpx
import pytest

import src.client.groq_client as gc_module
from src.client.embedder_client import EmbedderClient
from src.client.groq_client import GroqClient
from src.settings import Settings
from src.utils.exceptions.exceptions import (
    EmbeddingError,
    LLMError,
    LLMParseError,
    LLMRateLimitError,
)


@pytest.fixture(autouse=True)
def _reset_ratelimit_state():
    gc_module._last_request_at = 0.0
    gc_module._requests_budget = None
    gc_module._requests_reset_at = 0.0
    gc_module._tokens_budget = None
    gc_module._tokens_reset_at = 0.0
    gc_module._token_window.clear()
    yield


def make_settings(api_key="test-key", model="mock-llm"):
    return Settings(
        groq_api_key=api_key,
        groq_base_url="https://api.groq.com/openai/v1",
        llm_model=model,
        embedding_model="fake",
    )


class FakeResponse:
    def __init__(self, status_code=200, json_data=None) -> None:
        self.status_code = status_code
        self._json_data = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json_data


class FakeTransport:
    """httpx transport returning scripted responses."""

    def __init__(self, responses) -> None:
        self._responses = list(responses)
        self.request_count = 0

    async def handle_async_request(self, request):
        self.request_count += 1
        return self._responses.pop(0)


def _client_with(responses) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=FakeTransport(responses),
        base_url="https://api.groq.com/openai/v1",
    )


def _ok_response(content: str) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def _status_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, json={})


async def test_create_completion_success():
    client = GroqClient(make_settings())
    client._client = _client_with([_ok_response("the answer")])
    result = await client.create_completion(messages=[{"role": "user", "content": "hi"}])
    assert result["content"] == "the answer"


async def test_create_completion_no_api_key():
    client = GroqClient(make_settings(api_key=""))
    with pytest.raises(LLMError):
        await client.create_completion(messages=[])


async def test_create_completion_5xx_raises_after_retries():
    client = GroqClient(make_settings())
    responses = [_status_response(s) for s in [500, 500, 500, 500, 500]]
    client._client = _client_with(responses)
    with pytest.raises(LLMError):
        await client.create_completion(messages=[{"role": "user", "content": "hi"}])


async def test_parse_json_completion_valid():
    client = GroqClient(make_settings())
    payload = {"answer": "synth", "citations": []}
    client._client = _client_with([_ok_response(json.dumps(payload))])
    result = await client.parse_json_completion(messages=[])
    assert result["answer"] == "synth"


async def test_parse_json_completion_invalid_json():
    client = GroqClient(make_settings())
    client._client = _client_with([_ok_response("this is not json"), _ok_response("still not json")])
    with pytest.raises(LLMParseError):
        await client.parse_json_completion(messages=[])


async def test_parse_json_completion_empty_content():
    client = GroqClient(make_settings())
    client._client = _client_with([_ok_response(""), _ok_response("")])
    with pytest.raises(LLMParseError):
        await client.parse_json_completion(messages=[])


async def test_parse_json_completion_non_object():
    client = GroqClient(make_settings())
    client._client = _client_with([_ok_response("[1,2,3]"), _ok_response("[4,5,6]")])
    with pytest.raises(LLMParseError):
        await client.parse_json_completion(messages=[])


async def test_parse_json_completion_rate_limit_raises_without_reset_header():
    client = GroqClient(make_settings())
    responses = [_status_response(429)] * 5
    client._client = _client_with(responses)
    with pytest.raises(LLMRateLimitError):
        await client.parse_json_completion(messages=[])
    assert client._client._transport.request_count == 1


async def test_rate_limit_long_reset_raises_immediately():
    client = GroqClient(make_settings())
    throttled = httpx.Response(429, json={}, headers={"x-ratelimit-reset-tokens": "120s"})
    client._client = _client_with([throttled])
    with pytest.raises(LLMRateLimitError):
        await client.create_completion(messages=[{"role": "user", "content": "hi"}])
    assert client._client._transport.request_count == 1


async def test_create_completion_retries_after_short_rate_limit_reset():
    client = GroqClient(make_settings())
    throttled = httpx.Response(
        429,
        json={},
        headers={"x-ratelimit-reset-tokens": "1.0s", "x-ratelimit-remaining-tokens": "0"},
    )
    client._client = _client_with([throttled, _ok_response("the answer")])
    result = await client.create_completion(messages=[{"role": "user", "content": "hi"}])
    assert result["content"] == "the answer"
    assert client._client._transport.request_count == 2


async def test_rate_limit_token_headers_tracked():
    client = GroqClient(make_settings())
    ok = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "the answer"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
        headers={
            "x-ratelimit-remaining-tokens": "670",
            "x-ratelimit-reset-tokens": "12.0s",
        },
    )
    client._client = _client_with([ok])
    await client.create_completion(messages=[{"role": "user", "content": "hi"}])
    assert gc_module._tokens_budget == 670
    assert gc_module._tokens_reset_at > 0


async def test_create_completion_records_usage_on_success():
    recorded = []

    async def recorder(usage):
        recorded.append(usage)

    client = GroqClient(make_settings())
    client.usage_recorder = recorder
    client._client = _client_with([_ok_response("the answer")])
    result = await client.create_completion(
        messages=[{"role": "user", "content": "hi"}], task="qa_answer"
    )
    assert result["content"] == "the answer"
    assert len(recorded) == 1
    usage = recorded[0]
    assert usage["task"] == "qa_answer"
    assert usage["model"] == "mock-llm"
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["total_tokens"] == 15
    assert usage["success"] is True
    assert usage["latency_ms"] >= 0


async def test_create_completion_records_usage_on_failure():
    recorded = []

    async def recorder(usage):
        recorded.append(usage)

    client = GroqClient(make_settings())
    client.usage_recorder = recorder
    responses = [_status_response(s) for s in [500, 500, 500, 500, 500]]
    client._client = _client_with(responses)
    with pytest.raises(LLMError):
        await client.create_completion(messages=[{"role": "user", "content": "hi"}])
    assert len(recorded) == 1
    assert recorded[0]["success"] is False
    assert recorded[0]["task"] is None
    assert recorded[0]["total_tokens"] is None


async def test_create_completion_recorder_error_is_swallowed():
    async def recorder(usage):
        raise RuntimeError("recorder boom")

    client = GroqClient(make_settings())
    client.usage_recorder = recorder
    client._client = _client_with([_ok_response("the answer")])
    result = await client.create_completion(messages=[{"role": "user", "content": "hi"}])
    assert result["content"] == "the answer"


async def test_parse_json_completion_passes_task_to_completion():
    recorded = []

    async def recorder(usage):
        recorded.append(usage)

    client = GroqClient(make_settings())
    client.usage_recorder = recorder
    payload = {"answer": "synth", "citations": []}
    client._client = _client_with([_ok_response(json.dumps(payload))])
    result = await client.parse_json_completion(messages=[], task="themes")
    assert result["answer"] == "synth"
    assert recorded[0]["task"] == "themes"


async def test_groq_network_error():
    client = GroqClient(make_settings())

    class BrokenTransport:
        async def handle_async_request(self, request):
            raise httpx.ConnectError("unreachable")

    client._client = httpx.AsyncClient(transport=BrokenTransport())
    with pytest.raises(LLMError):
        await client.create_completion(messages=[{"role": "user", "content": "hi"}])


async def test_groq_closes_client():
    client = GroqClient(make_settings())
    await client.close()


def test_embedder_client_uses_model(monkeypatch):
    embedder = EmbedderClient(make_settings())
    recorded = {}

    class FakeST:
        def encode(self, texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True):
            recorded["texts"] = texts
            import numpy as np

            return np.array([[0.1] * 384])

    monkeypatch.setattr(embedder, "_load", lambda: FakeST())
    result = embedder.embed_one("hello")
    assert len(result) == 384
    assert recorded["texts"] == ["hello"]


def test_embedder_load_failure(monkeypatch):
    embedder = EmbedderClient(make_settings())

    def fail_load():
        raise RuntimeError("model download failed")

    monkeypatch.setattr(embedder, "_load", fail_load)
    with pytest.raises(EmbeddingError):
        embedder.embed_one("hello")


def test_embedder_error_wrapped(monkeypatch):
    embedder = EmbedderClient(make_settings())

    class BrokenST:
        def encode(self, *args, **kwargs):
            raise RuntimeError("encode failed")

    monkeypatch.setattr(embedder, "_load", lambda: BrokenST())
    with pytest.raises(EmbeddingError):
        embedder.embed(["a", "b"])