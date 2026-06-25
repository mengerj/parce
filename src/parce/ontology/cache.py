"""On-disk cache for free-text → ontology-term resolutions.

Resolution hits a remote service (OLS) and is stable over time, so results are
memoised to a small JSON file: repeat ingests of the same source don't re-query,
and a run is reproducible offline once its terms are cached. Negative results
(text that resolved to nothing) are cached too, so unresolvable strings aren't
retried on every run — delete the cache file to force re-resolution after the
resolver improves.

The cache is process-local and guarded by a lock; it is *not* an IPC-safe store.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path

from parce.ontology.base import ResolvedTerm

logger = logging.getLogger(__name__)


class ResolutionCache:
    """A JSON-backed ``key -> (ResolvedTerm | None)`` cache.

    Loaded eagerly from ``path`` if it exists; written back atomically on each
    ``set``. A *missing* key (never resolved) is distinct from a key cached as
    ``None`` (resolved to nothing): :meth:`get` reports which via its first
    return value.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, ResolvedTerm | None] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable ontology cache %s: %s", self._path, exc)
            return
        for key, value in raw.items():
            self._data[key] = None if value is None else ResolvedTerm(**value)

    def get(self, key: str) -> tuple[bool, ResolvedTerm | None]:
        """Return ``(present, value)``: ``present`` is False on a cache miss."""
        with self._lock:
            if key not in self._data:
                return False, None
            return True, self._data[key]

    def set(self, key: str, value: ResolvedTerm | None) -> None:
        """Cache ``value`` (possibly ``None``) under ``key`` and persist."""
        with self._lock:
            self._data[key] = value
            self._flush()

    def _flush(self) -> None:
        serialisable = {
            key: (None if term is None else asdict(term)) for key, term in self._data.items()
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(serialisable, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)
