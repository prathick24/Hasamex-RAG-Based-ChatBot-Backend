from src.services.cache import (
    LRUCache,
    acached_result,
    cached_result,
    clear_cache,
    make_cache_key,
    purge_by_prefix,
)


def test_lru_cache_eviction():
    cache = LRUCache(maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    cache.set("c", 3)
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_lru_cache_move_to_end():
    cache = LRUCache(maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)
    _ = cache.get("a")
    cache.set("c", 3)
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_make_cache_key_deterministic():
    k1 = make_cache_key("task", "model", "question", [1, 2, 3])
    k2 = make_cache_key("task", "model", "question", [1, 2, 3])
    assert k1 == k2


def test_make_cache_key_differs_for_different_input():
    k1 = make_cache_key("task", 1)
    k2 = make_cache_key("task", 2)
    assert k1 != k2


def test_cached_result_cache_hit():
    clear_cache()
    counter = {"count": 0}

    def producer() -> dict:
        counter["count"] += 1
        return {"data": 42}

    key = make_cache_key("test_cached_result", 1)
    result1 = cached_result(key, producer)
    result2 = cached_result(key, producer)
    assert result1 == {"data": 42}
    assert result2 == {"data": 42}
    assert counter["count"] == 1


def test_clear_cache():
    clear_cache()
    key = make_cache_key("test_clear")
    cached_result(key, lambda: {"a": 1})
    clear_cache()
    counter = {"count": 0}
    cached_result(key, lambda: counter.update({"count": 1}) or {"a": 2})
    assert counter["count"] == 1


async def test_acached_result_cache_hit():
    clear_cache()
    counter = {"count": 0}

    async def producer() -> dict:
        counter["count"] += 1
        return {"data": 42}

    key = make_cache_key("test_acached_result", 1)
    result1 = await acached_result(key, producer)
    result2 = await acached_result(key, producer)
    assert result1 == {"data": 42}
    assert result2 == {"data": 42}
    assert counter["count"] == 1


def test_purge_by_prefix():
    clear_cache()
    cached_result("interview_guide_batch::a.txt::aaa", lambda: {"data": 1})
    cached_result("interview_guide_batch::b.txt::bbb", lambda: {"data": 2})
    cached_result("other::ccc", lambda: {"data": 3})
    assert purge_by_prefix("interview_guide_batch::b.txt::") == 1
    assert purge_by_prefix("interview_guide_batch::a.txt::") == 1
    assert purge_by_prefix("interview_guide_batch::") == 0
    assert purge_by_prefix("other::") == 1