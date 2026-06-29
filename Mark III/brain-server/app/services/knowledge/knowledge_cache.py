"""MARK III — Knowledge Cache — LRU cache for recently accessed vault documents."""
from __future__ import annotations
from collections import OrderedDict
from threading import Lock
from typing import Optional


class KnowledgeCache:
    def __init__(self, max_size: int = 50) -> None:
        self._cache: OrderedDict = OrderedDict()
        self._max   = max_size
        self._lock  = Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def set(self, key: str, value: str) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        return len(self._cache)
