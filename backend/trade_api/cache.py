"""Bounded in-process response cache (L1).

Keyed on route parameters *and* the dataset version token, so a rebuild of an
underlying partition invalidates dependent entries without any explicit purge.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable

import orjson

from .config import get_settings


class LruCache:
    def __init__(self, max_entries: int, max_bytes: int):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._data: OrderedDict[str, tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return entry[0]

    def put(self, key: str, value: Any) -> None:
        try:
            size = len(orjson.dumps(value, default=str))
        except TypeError:
            size = 1024
        if size > self.max_bytes:
            return
        with self._lock:
            if key in self._data:
                self._bytes -= self._data[key][1]
                del self._data[key]
            self._data[key] = (value, size)
            self._bytes += size
            while self._data and (len(self._data) > self.max_entries or self._bytes > self.max_bytes):
                _, (_, evicted) = self._data.popitem(last=False)
                self._bytes -= evicted

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._bytes = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._data),
                "bytes": self._bytes,
                "hits": self.hits,
                "misses": self.misses,
            }


_cache: LruCache | None = None
_cache_lock = threading.Lock()


def get_cache() -> LruCache:
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                settings = get_settings()
                _cache = LruCache(settings.lru_cache_entries, settings.lru_cache_max_bytes)
    return _cache


def cached(key: str, producer: Callable[[], Any]) -> Any:
    cache = get_cache()
    hit = cache.get(key)
    if hit is not None:
        return hit
    value = producer()
    cache.put(key, value)
    return value
