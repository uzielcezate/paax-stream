"""
app/providers/piped/provider.py
PipedProvider — concrete StreamProvider implementation for Piped.

Wires together:
  - client.py    — fetches raw data from Piped instances
  - selector.py  — ranks and picks the best audio stream

provider_manager holds and calls this class.
Routes never import this file directly.
"""
from typing import List

from app.providers.base import StreamProvider, ResolvedStream, AudioFormat, ProviderStatus
from app.providers.piped.client import fetch_streams
from app.providers.piped.selector import select_best, list_all
from app.providers.piped.instances import get_instances
from app.utils.logging import get_logger

log = get_logger(__name__)

_PROVIDER_NAME = "piped"


class PipedProvider(StreamProvider):
    """
    Stream provider backed by the Piped API.

    Tries configured Piped instances in order until one succeeds.
    Returns normalised ResolvedStream / AudioFormat objects.
    """

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    # ── StreamProvider interface ──────────────────────────────────────────────

    async def resolve_stream(self, video_id: str) -> ResolvedStream:
        """
        Resolve the best audio stream for video_id via Piped.

        Raises provider-level exceptions on failure so provider_manager
        can decide whether to fall back to Invidious.
        """
        log.info("[PipedProvider] resolve_stream videoId=%s", video_id)

        data         = await fetch_streams(video_id)
        audio_streams = data.get("audioStreams") or []

        log.info(
            "[PipedProvider] videoId=%s audioStreams=%d",
            video_id, len(audio_streams),
        )

        best = select_best(audio_streams)

        log.info(
            "[PipedProvider] Selected mimeType=%s bitrate=%d container=%s videoId=%s",
            best.mime_type, best.bitrate, best.container, video_id,
        )

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
        Return all audio formats for video_id, sorted by preference.
        """
        log.info("[PipedProvider] resolve_formats videoId=%s", video_id)

        data          = await fetch_streams(video_id)
        audio_streams = data.get("audioStreams") or []
        formats       = list_all(audio_streams)

        log.info(
            "[PipedProvider] videoId=%s audio_formats=%d",
            video_id, len(formats),
        )

        return formats

    def status(self) -> ProviderStatus:
        instances = get_instances()
        return ProviderStatus(
            name=self.name,
            available=True,
            base_url=instances[0] if instances else "",
            notes=f"primary provider — {len(instances)} instance(s) configured",
        )
