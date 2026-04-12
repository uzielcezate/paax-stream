"""
app/providers/youtube_ipv6_proxy/_cdn_cache.py
In-memory TTL cache for resolved CDN URLs.

The provider stores the resolved ``ResolvedAudio`` here after yt-dlp
extraction.  The ``/stream/{videoId}`` route reads it to avoid
re-resolving on every range-request from the Flutter client.

This is distinct from the top-level stream_cache (which caches the
provider *response* payload).  This cache stores the *raw CDN URL*
that must never be exposed to the client.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)


class CdnUrlCache:
    """Simple TTL dict for ResolvedAudio objects, keyed by video_id."""

    def __init__(self, ttl: int = 0) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        # Default TTL is the same as in-memory stream cache
        self._ttl = ttl or settings.CACHE_TTL_SECONDS

    def get(self, video_id: str) -> Any:
        entry = self._store.get(video_id)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            del self._store[video_id]
            return None
        return entry["data"]

    def set(self, video_id: str, resolved_audio: Any) -> None:
        self._store[video_id] = {
            "data":       resolved_audio,
            "expires_at": time.time() + self._ttl,
        }
        log.debug("[CdnCache] Stored CDN URL for %s (TTL %ds)", video_id, self._ttl)

    def delete(self, video_id: str) -> None:
        self._store.pop(video_id, None)


cdn_cache = CdnUrlCache()
