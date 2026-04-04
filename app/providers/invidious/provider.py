"""
app/providers/invidious/provider.py
InvidiousProvider — concrete StreamProvider implementation.

Wires together client.py (HTTP) + selector.py (format ranking)
and satisfies the StreamProvider interface from providers/base.py.

The provider_manager holds and calls this class.
Routes never import this file directly.
"""
from typing import List

from app.config import INVIDIOUS_BASE_URL, PROVIDER_NAME
from app.providers.base import StreamProvider, ResolvedStream, AudioFormat, ProviderStatus
from app.providers.invidious.client import fetch_video_info, validate_video_id
from app.providers.invidious.selector import select_best, list_all
from app.utils.logging import get_logger
from app.utils.errors import NoAudioFormatsError, InvalidVideoIdError

log = get_logger(__name__)


class InvidiousProvider(StreamProvider):
    """
    Stream provider backed by an Invidious instance.

    Uses GET /api/v1/videos/{videoId}?local=true so stream URLs
    route through Invidious rather than directly to googlevideo.com.
    """

    @property
    def name(self) -> str:
        return PROVIDER_NAME  # "invidious-nerdvpn" from config

    # ── StreamProvider interface ──────────────────────────────────────────────

    async def resolve_stream(self, video_id: str) -> ResolvedStream:
        """
        Fetch Invidious video info and return the best audio stream.

        Raises:
          InvalidVideoIdError      — malformed videoId
          InvidiousTimeoutError    — upstream timeout
          InvidiousUpstreamError   — non-200 / non-JSON upstream
          NoAudioFormatsError      — no usable audio format
        """
        log.info("[InvidiousProvider] resolve_stream videoId=%s", video_id)
        info        = await fetch_video_info(video_id)
        raw_formats = [
            f for f in (info.get("adaptiveFormats") or [])
            if (f.get("type") or "").lower().startswith("audio/") and f.get("url")
        ]

        log.info(
            "[InvidiousProvider] videoId=%s total_adaptive=%d audio_only=%d",
            video_id,
            len(info.get("adaptiveFormats") or []),
            len(raw_formats),
        )

        if not raw_formats:
            raise NoAudioFormatsError(f"No audio formats for videoId={video_id}")

        best = select_best(raw_formats)

        return ResolvedStream(
            video_id=video_id,
            provider=self.name,
            stream_url=best.url,
            mime_type=best.mime_type,
            container=best.container,
            bitrate=best.bitrate,
        )

    async def resolve_formats(self, video_id: str) -> List[AudioFormat]:
        """
        Fetch and return all audio formats, sorted by tier then bitrate.
        """
        log.info("[InvidiousProvider] resolve_formats videoId=%s", video_id)
        info        = await fetch_video_info(video_id)
        raw_formats = info.get("adaptiveFormats") or []
        formats     = list_all(raw_formats)
        log.info(
            "[InvidiousProvider] videoId=%s audio_formats=%d",
            video_id, len(formats),
        )
        return formats

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            available=True,
            base_url=INVIDIOUS_BASE_URL,
            notes="local=true — stream URLs proxied through Invidious",
        )
