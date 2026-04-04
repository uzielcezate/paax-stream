"""
app/providers/youtube_local_mp4/provider.py
YouTubeLocalMP4Provider — concrete StreamProvider using yt-dlp locally.

Wires together:
  - client.py   — async yt-dlp extraction (runs in thread pool)
  - selector.py — MP4 format ranking (144p → 240p → 360p priority)

provider_manager holds and calls this class.
Routes never import this file directly.

Design philosophy:
  "YouTube with a Spotify-style mask" — music-first UI, backend-resolved
  low-resolution MP4 delivery. No public proxy instances. No client-side
  stream resolution. Everything runs inside the Railway backend.
"""
from typing import List

from app.providers.base import StreamProvider, ResolvedStream, AudioFormat, ProviderStatus
from app.providers.youtube_local_mp4.client import fetch_formats
from app.providers.youtube_local_mp4.selector import select_best, list_candidates, VideoFormat
from app.utils.logging import get_logger

log = get_logger(__name__)

_PROVIDER_NAME = "youtube_local_mp4"


def _video_to_audio_format(vf: VideoFormat) -> AudioFormat:
    """
    Bridge between VideoFormat (local type) and AudioFormat (base.py type).
    The public contract uses AudioFormat everywhere; we re-use url/mime/bitrate
    and add height via the mimeType string so it survives the base contract.
    """
    # We set mime_type to "video/mp4" — provider name makes format clear
    return AudioFormat(
        mime_type=vf.mime_type,   # "video/mp4"
        container=vf.container,   # "mp4"
        bitrate=vf.bitrate,
        url=vf.url,
    )


class YouTubeLocalMP4Provider(StreamProvider):
    """
    First-party stream provider — resolves YouTube low-res MP4 directly
    in the backend via yt-dlp. No public proxy instances used.

    Active for Phase 5.
    """

    @property
    def name(self) -> str:
        return _PROVIDER_NAME

    # ── StreamProvider interface ──────────────────────────────────────────────

    async def resolve_stream(self, video_id: str) -> ResolvedStream:
        """
        Extract YouTube formats and select the best MP4 (144p / 240p / 360p).
        Returns a ResolvedStream with video/mp4 mimeType and the chosen height.
        """
        log.info("[YTLocalMP4Provider] resolve_stream videoId=%s", video_id)

        formats = await fetch_formats(video_id)
        best    = select_best(formats)

        log.info(
            "[YTLocalMP4Provider] Selected height=%dp format_id=%s bitrate=%d videoId=%s",
            best.height, best.format_id, best.bitrate, video_id,
        )

        return ResolvedStream(
            video_id=video_id,
            provider=self.name,
            stream_url=best.url,
            mime_type=best.mime_type,
            container=best.container,
            bitrate=best.bitrate,
            height=best.height,
        )

    async def resolve_formats(self, video_id: str) -> List[AudioFormat]:
        """
        Return all MP4 low-res candidate formats, sorted by priority.
        Uses AudioFormat as the common base type (url, mime_type, container, bitrate).
        """
        log.info("[YTLocalMP4Provider] resolve_formats videoId=%s", video_id)

        formats    = await fetch_formats(video_id)
        candidates = list_candidates(formats)

        log.info(
            "[YTLocalMP4Provider] videoId=%s mp4_candidates=%d",
            video_id, len(candidates),
        )

        return [_video_to_audio_format(c) for c in candidates]

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            available=True,
            base_url="https://www.youtube.com",
            notes="first-party yt-dlp extraction; MP4 144p/240p/360p priority; no public proxies",
        )
