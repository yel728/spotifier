from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class CacheHit(Generic[V]):
    value: V
    age: float


@dataclass
class _Entry(Generic[V]):
    value: V
    stored_at: float
    expires_at: float


class TTLCache(Generic[K, V]):
    """Small thread-safe monotonic TTL cache with bounded LRU eviction."""

    def __init__(self, max_entries: int):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: K) -> CacheHit[V] | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return CacheHit(entry.value, now - entry.stored_at)

    def set(self, key: K, value: V, ttl: float) -> None:
        if ttl <= 0:
            self.invalidate(key)
            return
        now = time.monotonic()
        with self._lock:
            self._entries[key] = _Entry(value, now, now + ttl)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, key: K) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def values(self) -> list[V]:
        now = time.monotonic()
        with self._lock:
            expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
            for key in expired:
                del self._entries[key]
            return [entry.value for entry in self._entries.values()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
