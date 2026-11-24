import threading
import time
from typing import Any


class TTLCache:
    """Cache in memoria minimale con scadenza, thread-safe."""

    def __init__(self, ttl_seconds: int, max_items: int = 2000):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if expires < time.monotonic():
                del self._data[key]
                return None
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self.max_items:
                now = time.monotonic()
                for k in [k for k, (exp, _) in self._data.items() if exp < now]:
                    del self._data[k]
                if len(self._data) >= self.max_items:
                    self._data.pop(next(iter(self._data)))
            self._data[key] = (time.monotonic() + self.ttl, value)
