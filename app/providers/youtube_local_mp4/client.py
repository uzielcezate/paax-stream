"""
app/providers/youtube_local_mp4/client.py
Local YouTube format extractor using yt-dlp.

Extracts available formats for a YouTube videoId and returns format metadata.
Does NOT stream or download video content — only resolves direct URLs.

This runs entirely in the backend (Railway). No public proxy instances used.
"""
import asyncio
import functools
from typing import Any, Dict, List

from app.utils.logging import get_logger
from app.utils.errors import InvalidVideoIdError, NoAudioFormatsError, InvidiousUpstreamError

log = get_logger(__name__)

# yt-dlp options: list formats only, no download, no disk writes
_YDL_OPTS: Dict[str, Any] = {
    "quiet":            True,
    "no_warnings":      True,
    "skip_download":    True,
    "noplaylist":       True,
    "extract_flat":     False,
    # Prefer a browser-like extractor to reduce bot detection
    "extractor_args":   {"youtube": {"player_client": ["web"]}},
}


def _validate_video_id(video_id: str) -> None:
    vid = video_id.strip()
    if (
        not vid
        or len(vid) < 5
        or len(vid) > 16
        or not vid.replace("-", "").replace("_", "").isalnum()
    ):
        raise InvalidVideoIdError(f"Invalid videoId: '{video_id}'")


def _extract_sync(video_id: str) -> List[Dict[str, Any]]:
    """
    Synchronous yt-dlp extraction — runs in a thread pool executor.
    Returns the list of raw format dicts from the yt-dlp info dict.
    """
    try:
        import yt_dlp  # imported here to keep startup fast if optional
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Add 'yt-dlp' to requirements.txt."
        ) from exc

    url = f"https://www.youtube.com/watch?v={video_id}"
    log.info("[YTLocalMP4.client] Extracting formats for videoId=%s url=%s", video_id, url)

    with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
        try:
            info: Dict[str, Any] = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            log.error("[YTLocalMP4.client] yt-dlp DownloadError videoId=%s: %s", video_id, exc)
            raise InvidiousUpstreamError(0, str(exc)) from exc
        except Exception as exc:
            log.error("[YTLocalMP4.client] Unexpected extraction error videoId=%s: %s", video_id, exc)
            raise InvidiousUpstreamError(0, str(exc)) from exc

    formats: List[Dict[str, Any]] = info.get("formats") or []
    log.info(
        "[YTLocalMP4.client] Extraction OK videoId=%s total_formats=%d",
        video_id, len(formats),
    )
    return formats


async def fetch_formats(video_id: str) -> List[Dict[str, Any]]:
    """
    Async wrapper around the synchronous yt-dlp extraction.
    Runs in ThreadPoolExecutor so it does not block the event loop.

    Returns a list of raw format dicts (same shape as yt-dlp info['formats']).

    Raises:
      InvalidVideoIdError    — bad videoId
      InvidiousUpstreamError — yt-dlp extraction failed
      NoAudioFormatsError    — no formats returned at all
    """
    _validate_video_id(video_id)

    loop = asyncio.get_event_loop()
    formats = await loop.run_in_executor(
        None,  # default ThreadPoolExecutor
        functools.partial(_extract_sync, video_id),
    )

    if not formats:
        raise NoAudioFormatsError(f"yt-dlp returned no formats for videoId={video_id}")

    return formats
