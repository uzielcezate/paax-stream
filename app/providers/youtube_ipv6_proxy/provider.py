"""
app/providers/youtube_ipv6_proxy/provider.py
YouTubeIPv6ProxyProvider — concrete StreamProvider for the IPv6 proxy pipeline.

Architecture:
  - resolve_stream() returns a *proxy* URL (/stream/{videoId}) that the
    Flutter client will hit directly.  The actual CDN stream URL is never
    leaked to the client.
  - The /stream/ route (routes/stream.py) performs the real work: IPv6
    selection → session cookies → httpx streaming → HTTP 206.

This provider therefore acts as a "redirect-to-self" adapter that fits the
existing provider_manager / cache / fallback infrastructure.
"""
from __future__ import annotations

from typing import List

from app.providers.base import (
    AudioFormat,
    ProviderStatus,
    ResolvedStream,
    StreamProvider,
)
from app.providers.youtube_ipv6_proxy.resolver import (
    resolve_m4a_url,
    list_audio_formats as _list_audio_formats,
)
from app.providers.youtube_ipv6_proxy.ipv6_pool import pool_size, get_all_addresses
from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)

_PROVIDER_NAME = "youtube_ipv6_proxy"


class YouTubeIPv6ProxyProvider(StreamProvider):
    """
    Streaming proxy provider — resolves audio and tells the client
    to stream from our own ``/stream/{videoId}`` endpoint.

    Active for Phase 6.
    """

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    # ── StreamProvider interface ──────────────────────────────────────────────

    async def resolve_stream(self, video_id: str) -> ResolvedStream:
        """
        Resolve the M4A audio URL via yt-dlp, but return a *self-referencing*
        proxy URL so the Flutter client fetches from us, not the CDN.

        The ``stream_url`` field contains ``/stream/{video_id}`` which the
        Flutter client will use.  The actual CDN URL is stored in the
        in-memory cache for consumption by the /stream/ route.
        """
        log.info("[IPv6ProxyProvider] resolve_stream videoId=%s", video_id)

        resolved = await resolve_m4a_url(video_id)

        # Store the CDN URL in a module-level cache so /stream/ can use it
        # without re-resolving.
        from app.providers.youtube_ipv6_proxy._cdn_cache import cdn_cache
        cdn_cache.set(video_id, resolved)

        # Return a *proxy URL* to the client
        proxy_url = f"/stream/{video_id}"

        return ResolvedStream(
            video_id=video_id,
            provider=self.name,
            stream_url=proxy_url,
            mime_type=resolved.mime_type,
            container=resolved.container,
            bitrate=resolved.bitrate,
            height=0,  # audio-only
        )

    async def resolve_formats(self, video_id: str) -> List[AudioFormat]:
        """Return all audio-only formats for the debug endpoint."""
        log.info("[IPv6ProxyProvider] resolve_formats videoId=%s", video_id)

        raw_formats = await _list_audio_formats(video_id)

        return [
            AudioFormat(
                mime_type=f"audio/{f.get('ext', 'unknown')}",
                container=f.get("ext", "unknown"),
                bitrate=int(float(f.get("tbr") or f.get("abr") or 0) * 1000),
                url=f.get("url", ""),
            )
            for f in raw_formats
        ]

    def status(self) -> ProviderStatus:
        addrs = get_all_addresses()
        return ProviderStatus(
            name=self.name,
            available=True,
            base_url=settings.SOURCE_PLATFORM_URL,
            notes=(
                f"IPv6 proxy provider; {pool_size()} addresses "
                f"({addrs[0]} -> {addrs[-1]}); "
                f"itag 140 M4A priority; Redis session management"
            ),
        )
