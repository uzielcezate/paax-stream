"""
app/services/cache_service.py
In-memory TTL cache for resolved stream results.

Phase 1: simple dict + timestamp — no Redis, no persistence.
Cleared on service restart (acceptable for CDN-signed URLs that expire anyway).
"""
import time
from typing import Any, Optional, Dict

from app.config import CACHE_TTL_SECONDS
from app.utils.logging import get_logger

log = get_logger(__name__)


class StreamCache:
    """
    Thread-safe enough for asyncio single-process deployments.
    Each entry: { "data": <payload>, "expires_at": <unix timestamp> }
    """

    def __init__(self, ttl: int = CACHE_TTL_SECONDS) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._ttl   = ttl

    # ── public API ────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        """Return cached value or None on miss / expiry."""
        entry = self._store.get(key)
        if entry is None:
            log.debug("[Cache] MISS key=%s", key)
            return None
        if time.time() > entry["expires_at"]:
            del self._store[key]
            log.debug("[Cache] EXPIRED key=%s", key)
            return None
        log.info("[Cache] HIT key=%s (ttl_remaining=%.0fs)", key,
                 entry["expires_at"] - time.time())
        return entry["data"]

    def set(self, key: str, value: Any) -> None:
        """Store value with configured TTL."""
        self._store[key] = {
            "data":       value,
            "expires_at": time.time() + self._ttl,
        }
        log.info("[Cache] SET key=%s ttl=%ds", key, self._ttl)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def size(self) -> int:
        """Return number of (possibly stale) entries."""
        return len(self._store)

    def purge_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now   = time.time()
        stale = [k for k, v in self._store.items() if v["expires_at"] <= now]
        for k in stale:
            del self._store[k]
        if stale:
            log.debug("[Cache] Purged %d stale entries", len(stale))
        return len(stale)


# Singleton — imported once and shared across all requests
stream_cache = StreamCache()
