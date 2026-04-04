"""
app/providers/cobalt/provider.py
CobaltProvider — concrete StreamProvider implementation for Cobalt.

Wires together:
  - client.py   — POST requests to Cobalt instances with retry
  - selector.py — normalises the tunnel URL into AudioFormat / ResolvedStream

provider_manager holds and calls this class.
Routes never import this file directly.
"""
from typing import List

from app.providers.base import StreamProvider, ResolvedStream, AudioFormat, ProviderStatus
from app.providers.cobalt.client import fetch_tunnel
from app.providers.cobalt.selector import normalize_stream, list_formats
from app.providers.cobalt.instances import get_instances
from app.utils.logging import get_logger

log = get_logger(__name__)

_PROVIDER_NAME = "cobalt"


class CobaltProvider(StreamProvider):
    """
    Stream provider backed by Cobalt.

    Cobalt is a POST-based resolver that returns a single pre-selected
    audio tunnel URL. The provider normalises this into the same
    ResolvedStream / AudioFormat shape used by all providers.
    """

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    # ── StreamProvider interface ──────────────────────────────────────────────

    async def resolve_stream(self, video_id: str) -> ResolvedStream:
        """
        Resolve a playable audio tunnel URL for video_id via Cobalt.

        Raises provider-level exceptions on failure so provider_manager
        can fall back to Invidious.
        """
        log.info("[CobaltProvider] resolve_stream videoId=%s", video_id)

        data = await fetch_tunnel(video_id)
        fmt  = normalize_stream(data, video_id)

        log.info(
            "[CobaltProvider] Success videoId=%s mimeType=%s bitrate=%d",
            video_id, fmt.mime_type, fmt.bitrate,
        )

        return ResolvedStream(
            video_id=video_id,
            provider=self.name,
            stream_url=fmt.url,
            mime_type=fmt.mime_type,
            container=fmt.container,
            bitrate=fmt.bitrate,
        )

    async def resolve_formats(self, video_id: str) -> List[AudioFormat]:
        """
        Return a normalised single-element format list for video_id.
        Cobalt is a single-stream resolver, so there is exactly one entry.
        """
        log.info("[CobaltProvider] resolve_formats videoId=%s", video_id)

        data    = await fetch_tunnel(video_id)
        formats = list_formats(data, video_id)

        log.info(
            "[CobaltProvider] resolve_formats videoId=%s formats=%d",
            video_id, len(formats),
        )

        return formats

    def status(self) -> ProviderStatus:
        instances = get_instances()
        return ProviderStatus(
            name=self.name,
            available=True,
            base_url=instances[0] if instances else "",
            notes=f"primary provider — {len(instances)} instance(s) — audio/mp4 tunnel",
        )
