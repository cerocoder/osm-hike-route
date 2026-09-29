"""Per-route JSON cache with optional max age. Written on every put, same
incremental-write reasoning as place_info/cache.py."""
import json
import time
from pathlib import Path


class JsonCache:
    def __init__(self, path, now=time.time):
        self._path = Path(path)
        self._now = now
        self._data = {}
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
            except json.JSONDecodeError:
                self._data = {}

    def get_entry(self, key: str, max_age: float | None = None):
        """Returns (value, stored_at_epoch) or None if absent or older than
        max_age seconds (max_age=None means never expires)."""
        entry = self._data.get(key)
        if not isinstance(entry, dict) or "v" not in entry or "t" not in entry:
            return None
        if max_age is not None and self._now() - entry["t"] > max_age:
            return None
        return entry["v"], entry["t"]

    def put(self, key: str, value) -> float:
        stored_at = self._now()
        self._data[key] = {"t": stored_at, "v": value}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        return stored_at
