from __future__ import annotations

from nntpintel.statistics_cache import StatisticsCache


def test_cache_key_is_deterministic_and_namespaced() -> None:
    first = StatisticsCache.key("json", "/api/v1/statistics/servers?resolution=day")
    second = StatisticsCache.key("json", "/api/v1/statistics/servers?resolution=day")
    other = StatisticsCache.key("html", "/api/v1/statistics/servers?resolution=day")

    assert first == second
    assert first != other
    assert first.startswith("json:")


def test_cache_reuses_computed_value() -> None:
    cache = StatisticsCache(ttl_seconds=60, max_entries=8)
    calls = 0

    def compute() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    first, first_hit = cache.get_or_compute("key", compute)
    second, second_hit = cache.get_or_compute("key", compute)

    assert first == {"calls": 1}
    assert second == {"calls": 1}
    assert first_hit is False
    assert second_hit is True
    assert calls == 1


def test_cache_is_bounded() -> None:
    cache = StatisticsCache(ttl_seconds=60, max_entries=2)
    cache.get_or_compute("one", lambda: 1)
    cache.get_or_compute("two", lambda: 2)
    cache.get_or_compute("three", lambda: 3)

    assert len(cache._entries) == 2


def test_cache_rejects_invalid_configuration() -> None:
    for kwargs in ({"ttl_seconds": 0}, {"max_entries": 0}):
        try:
            StatisticsCache(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid cache configuration was accepted")
