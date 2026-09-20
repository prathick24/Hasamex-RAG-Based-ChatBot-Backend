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
from src.utils.exceptions.exceptions import LLMError, LLMParseError
from src.utils.logger import logger

_token_lock = asyncio.Lock()
_last_request_at = 0.0
_token_window: deque[tuple[float, float]] = deque()
_TOKEN_WINDOW_SECONDS = 60.0
_requests_budget: float | None = None
_requests_reset_at = 0.0


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
    """Refresh the request budget from Groq's x-ratelimit-* headers."""
    global _requests_budget, _requests_reset_at
    headers = response.headers
    requests_remaining = _parse_number(headers.get("x-ratelimit-remaining-requests"))
    requests_reset = _parse_seconds(headers.get("x-ratelimit-reset-requests"))
    if requests_remaining is not None:
        _requests_budget = requests_remaining
    if requests_reset is not None:
        _requests_reset_at = time.monotonic() + requests_reset


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
            global _last_request_at, _requests_budget
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

            _last_request_at = time.monotonic()
            response = await self._client.post(
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            _update_ratelimit_from(response)
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
        """Request the model to return valid JSON and parse it."""
        completion = await self.create_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            task=task,
        )
        try:
            content = completion["content"]
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise LLMParseError("Groq returned non-object JSON")
            return parsed
        except json.JSONDecodeError as exc:
            raise LLMParseError(f"Failed to parse Groq JSON response: {exc}") from exc

    async def close(self) -> None:
        await self._client.aclose()
