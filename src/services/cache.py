import hashlib
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

from src.settings import get_settings


class LRUCache:
    def __init__(self, maxsize: int = 128) -> None:
        self._maxsize = maxsize
        self._store: OrderedDict[str, Any] = OrderedDict()

    def get(self, key: str) -> Any | None:
        value = self._store.get(key)
        if value is not None:
            self._store.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


_cache = LRUCache()


def make_cache_key(*parts: Any) -> str:
    dumped = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def cached_result[T](key: str, producer: Callable[[], T]) -> T:
    cached = _cache.get(key)
    if cached is not None:
        return cached
    value = producer()
    _cache.set(key, value)
    return value


async def acached_result[T](key: str, producer: Callable[[], Awaitable[T]]) -> T:
    """Like cached_result but supports an async producer (used by LLM services)."""
    cached = _cache.get(key)
    if cached is not None:
        return cached
    value = await producer()
    _cache.set(key, value)
    return value


def clear_cache() -> None:
    _cache.clear()


def cache_enabled() -> bool:
    return get_settings().cache_llm_results
