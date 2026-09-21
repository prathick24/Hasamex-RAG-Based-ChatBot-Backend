import asyncio
import json
import re
import time
from collections import deque

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.settings import (
    GROQ_ESTIMATED_TOKENS_PER_REQUEST,
    GROQ_MIN_REQUEST_INTERVAL,
    GROQ_TOKEN_LIMIT,
    LLM_RETRY_MAX_ATTEMPTS,
    LLM_RETRY_WAIT_MAX,
    LLM_RETRY_WAIT_MIN,
    LLM_TIMEOUT_SECONDS,
    Settings,
)
from src.utils.exceptions.exceptions import LLMError, LLMParseError, LLMRateLimitError
from src.utils.logger import logger

_token_lock = asyncio.Lock()
_last_request_at = 0.0
_token_window: deque[tuple[float, float]] = deque()
_TOKEN_WINDOW_SECONDS = 60.0
_requests_budget: float | None = None
_requests_reset_at = 0.0
_tokens_budget: float | None = None
_tokens_reset_at = 0.0
_MAX_RATE_LIMIT_WAIT_SECONDS = 60.0
_MAX_429_RETRIES = 2


def _parse_number(value) -> float | None:
    """Extract the leading number from a header value (e.g. '6708')."""
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def _parse_seconds(value) -> float | None:
    """Parse a Groq reset header to seconds (e.g. '34.14s', '31m40.8s')."""
    if value is None:
        return None
    total = 0.0
    found = False
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", str(value).lower()):
        found = True
        multiplier = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}[unit]
        total += float(number) * multiplier
    return total if found else None


def _update_ratelimit_from(response) -> None:
    """Refresh the request and token budgets from Groq's x-ratelimit-* headers."""
    global _requests_budget, _requests_reset_at, _tokens_budget, _tokens_reset_at
    headers = response.headers
    requests_remaining = _parse_number(headers.get("x-ratelimit-remaining-requests"))
    requests_reset = _parse_seconds(headers.get("x-ratelimit-reset-requests"))
    tokens_remaining = _parse_number(headers.get("x-ratelimit-remaining-tokens"))
    tokens_reset = _parse_seconds(headers.get("x-ratelimit-reset-tokens"))
    if requests_remaining is not None:
        _requests_budget = requests_remaining
    if requests_reset is not None:
        _requests_reset_at = time.monotonic() + requests_reset
    if tokens_remaining is not None:
        _tokens_budget = tokens_remaining
    if tokens_reset is not None:
        _tokens_reset_at = time.monotonic() + tokens_reset


def _retry_after_seconds(response) -> float | None:
    """Service-defined wait before retrying a rate-limited request.

    Considers Retry-After and the token/request reset headers; returns the
    longest wait so the retry truly has headroom.
    """
    headers = response.headers
    candidates: list[float] = []

    retry_after = headers.get("retry-after")
    if retry_after:
        parsed = _parse_seconds(retry_after)
        if parsed is None:
            match = re.search(r"\d+(?:\.\d+)?", str(retry_after))
            if match:
                parsed = float(match.group())
        if parsed is not None and parsed > 0:
            candidates.append(parsed)

    for name in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        value = _parse_seconds(headers.get(name))
        if value is not None and value > 0:
            candidates.append(value)

    return max(candidates) if candidates else None


def _prune_token_window() -> None:
    """Drop token-window entries that have aged out of the rolling minute."""
    cutoff = time.monotonic() - _TOKEN_WINDOW_SECONDS
    while _token_window and _token_window[0][0] < cutoff:
        _token_window.popleft()


def _record_token_usage(total_tokens: float | None) -> None:
    """Record actual tokens consumed in the rolling token window."""
    if total_tokens and total_tokens > 0:
        _token_window.append((time.monotonic(), float(total_tokens)))
        _prune_token_window()


class GroqClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.groq_base_url
        self.api_key = settings.groq_api_key
        self.model = settings.llm_model
        self.timeout = LLM_TIMEOUT_SECONDS
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
        )
        self.usage_recorder = None

    @retry(
        stop=stop_after_attempt(LLM_RETRY_MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=LLM_RETRY_WAIT_MIN, max=LLM_RETRY_WAIT_MAX),
        retry=retry_if_exception(
            lambda exc: (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in (429, 500, 502, 503, 504)
            )
        ),
        reraise=True,
    )
    async def _post_completion(
        self,
        payload: dict,
        temperature: float,
        max_tokens: int,
        response_format: dict | None,
    ) -> dict:
        body: dict = {
            "model": self.model,
            "messages": payload["messages"],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        async with _token_lock:
            global _last_request_at, _requests_budget, _tokens_budget
            now = time.monotonic()

            delay = GROQ_MIN_REQUEST_INTERVAL - (now - _last_request_at)
            if delay > 0:
                await asyncio.sleep(delay)

            while True:
                _prune_token_window()
                if not _token_window:
                    break
                used = sum(total for _, total in _token_window)
                if used + GROQ_ESTIMATED_TOKENS_PER_REQUEST <= GROQ_TOKEN_LIMIT:
                    break
                oldest_expiry = _token_window[0][0] + _TOKEN_WINDOW_SECONDS
                remaining = oldest_expiry - time.monotonic()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                else:
                    _token_window.popleft()

            if _requests_budget is not None and _requests_budget <= 0:
                if time.monotonic() < _requests_reset_at:
                    await asyncio.sleep(_requests_reset_at - time.monotonic())
                _requests_budget = None

            if _tokens_budget is not None and _tokens_budget <= 0:
                if time.monotonic() < _tokens_reset_at:
                    await asyncio.sleep(_tokens_reset_at - time.monotonic())
                _tokens_budget = None

            _last_request_at = time.monotonic()
            for _attempt in range(_MAX_429_RETRIES):
                response = await self._client.post(
                    "/chat/completions",
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                _update_ratelimit_from(response)
                if response.status_code != 429:
                    break
                wait = _retry_after_seconds(response)
                if wait is None or wait >= _MAX_RATE_LIMIT_WAIT_SECONDS:
                    raise LLMRateLimitError(
                        "Groq rate limit reached"
                        + (f"; retry allowed in {wait:.0f}s" if wait is not None else "")
                    )
                logger.warning(
                    "groq_rate_limited_sleeping",
                    wait_seconds=round(wait, 1),
                    attempt=_attempt + 1,
                )
                await asyncio.sleep(wait + 0.5)
            else:
                raise LLMRateLimitError("Groq rate limit reached; retry allowed shortly")

            try:
                data = response.json()
            except ValueError:
                data = {}
            if response.status_code < 400:
                usage = data.get("usage") or {}
                total_tokens = usage.get("total_tokens")
                if total_tokens is None:
                    total_tokens = (usage.get("prompt_tokens") or 0) + (
                        usage.get("completion_tokens") or 0
                    )
                _record_token_usage(total_tokens)
        response.raise_for_status()
        return data

    async def create_completion(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 1024,
        response_format: dict | None = None,
        task: str | None = None,
    ) -> dict:
        if not self.api_key:
            raise LLMError("GROQ_API_KEY is not configured")

        payload = {"messages": messages}
        start = time.monotonic()
        try:
            logger.info("groq_request", model=self.model, messages=len(messages))
            data = await self._post_completion(payload, temperature, max_tokens, response_format)
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            logger.info(
                "groq_completion",
                model=self.model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            if not content:
                raise LLMParseError("Empty content returned by Groq")
            await self._record_usage(task, usage, start, success=True)
            return {"content": content, "raw": data}
        except LLMRateLimitError:
            await self._record_usage(task, {}, start, success=False)
            raise
        except LLMParseError:
            await self._record_usage(task, data.get("usage", {}), start, success=False)
            raise
        except httpx.HTTPStatusError as exc:
            await self._record_usage(task, {}, start, success=False)
            raise LLMError(f"Groq request failed with status {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            await self._record_usage(task, {}, start, success=False)
            raise LLMError(f"Groq request failed: {exc}") from exc

    async def _record_usage(
        self,
        task: str | None,
        usage: dict,
        start: float,
        success: bool,
    ) -> None:
        """Best-effort: report each LLM call to the injected usage recorder."""
        if self.usage_recorder is None:
            return
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens
        try:
            await self.usage_recorder(
                {
                    "task": task,
                    "model": self.model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": round((time.monotonic() - start) * 1000),
                    "success": success,
                }
            )
        except Exception:
            logger.warning("usage_recorder_failed", exc_info=True)

    async def parse_json_completion(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        task: str | None = None,
    ) -> dict:
        """Request the model to return valid JSON and parse it.

        Providers occasionally emit slightly malformed JSON even in JSON mode
        (a stray comma, a markdown fence). Retry once with the same prompts
        before giving up so a transient slip does not fail an entire topic.
        """
        last_error = None
        for _attempt in range(2):
            completion = await self.create_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                task=task,
            )
            try:
                content = completion["content"].strip()
                if content.startswith("```"):
                    content = content.strip("`")
                    if content.startswith("json"):
                        content = content[4:].lstrip()
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise LLMParseError("LLM returned non-object JSON")
                return parsed
            except (json.JSONDecodeError, LLMParseError) as exc:
                last_error = exc
                logger.warning("llm_json_retry", task=task, attempt=_attempt + 1)
        raise LLMParseError(f"Failed to parse LLM JSON response after retry: {last_error}")

    async def close(self) -> None:
        await self._client.aclose()
