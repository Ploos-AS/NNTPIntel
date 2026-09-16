from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

T = TypeVar("T")


@dataclass(frozen=True)
class CacheEntry(Generic[T]):
    value: T
    expires_at: float


class StatisticsCache:
    """Small deterministic in-process cache for public statistics responses.

    Cache keys are derived from the normalized request path/query supplied by the
    HTTP layer. Entries expire after a short TTL so completed rollups become
    visible without an explicit invalidation channel. The cache is intentionally
    bounded to protect a long-running public service from unbounded key growth.
    """

    def __init__(self, *, ttl_seconds: float = 30.0, max_entries: int = 512) -> None:
        if ttl_seconds <= 0:
            raise ValueError("cache ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("cache max_entries must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, CacheEntry[object]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(namespace: str, canonical_request: str) -> str:
        digest = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        return f"{namespace}:{digest}"

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> tuple[T, bool]:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now:
                return cast(T, entry.value), True
            if entry is not None:
                self._entries.pop(key, None)

        value = compute()
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            if len(self._entries) >= self.max_entries:
                oldest_key = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest_key, None)
            self._entries[key] = CacheEntry(value=value, expires_at=expires_at)
        return value, False

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
