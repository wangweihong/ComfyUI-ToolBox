"""Byte-bounded, thread-safe caches. Cache values never own browser state."""
from collections import OrderedDict
import threading

import numpy as np


def byte_size(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, np.ndarray):
        return value.nbytes
    if isinstance(value, (bytes, str)):
        return len(value.encode() if isinstance(value, str) else value)
    if isinstance(value, dict):
        return sum(byte_size(v, seen) for v in value.values())
    if isinstance(value, (tuple, list)):
        return sum(byte_size(v, seen) for v in value)
    if hasattr(value, "__dict__") and value.__class__.__module__.startswith(__package__):
        return byte_size(vars(value), seen)
    return 64


class ByteLRU:
    def __init__(self, max_bytes, max_items=64):
        self.max_bytes = max_bytes
        self.max_items = max_items
        self._items = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return self._items[key]

    def contains(self, key):
        """Checking cache validity is not a use of a preview snapshot."""
        with self._lock:
            return key in self._items

    def put(self, key, value):
        with self._lock:
            self._items.pop(key, None)
            if byte_size(value) <= self.max_bytes:
                self._items[key] = value
            self._trim()
        return value

    def _trim(self):
        while self._items and (len(self._items) > self.max_items or self.bytes > self.max_bytes):
            self._items.popitem(last=False)

    def reweigh(self):
        with self._lock:
            self._trim()

    def clear(self):
        with self._lock:
            self._items.clear()

    @property
    def bytes(self):
        with self._lock:
            return byte_size(self._items)

    def stats(self):
        with self._lock:
            return {"items": len(self._items), "bytes": self.bytes, "limit": self.max_bytes}


REGION_CACHE = ByteLRU(256 * 1024**2, 128)
SCENE_CACHE = ByteLRU(1024 * 1024**2, 4)
SESSION_CACHE = ByteLRU(512 * 1024**2, 8)
