"""
app/providers/youtube_ipv6_proxy/resolver.py
Extracts the itag-140 (.m4a, 128 kbps AAC) stream URL using yt-dlp.

itag 140 is the standard YouTube audio-only M4A stream:
  - Container : mp4 (M4A)
  - Codec     : mp4a.40.2 (AAC-LC)
  - Bitrate   : ~128 kbps
  - Seekable  : yes (single-segment, supports byte-range)

Falls back to the best available audio-only format if itag 140
is not present (age-restricted, live, etc.).

The resolved URL is an *upstream CDN URL* — callers must NOT expose
it to the client.  It is consumed internally by the streaming route.
"""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.config import settings
from app.utils.logging import get_logger
from app.utils.errors import (
    InvalidVideoIdError,
    NoAudioFormatsError,
    InvidiousUpstreamError,
)

log = get_logger(__name__)

# ── Target itag ───────────────────────────────────────────────────────────────
_ITAG_M4A_128 = 140   # 128 kbps AAC in MP4 container


@dataclass(frozen=True)
class ResolvedAudio:
    """Result of a successful audio URL resolution."""
    video_id:     str
    stream_url:   str           # direct CDN URL — do NOT leak to client
    mime_type:    str           # "audio/mp4"
    container:    str           # "m4a"
    bitrate:      int           # bps
    content_length: Optional[int] = None   # bytes, if reported by yt-dlp
    itag:         Optional[int]   = None


# ── yt-dlp options ────────────────────────────────────────────────────────────
_YDL_OPTS: Dict[str, Any] = {
    "quiet":         True,
    "no_warnings":   True,
    "skip_download": True,
    "noplaylist":    True,
    "extract_flat":  False,
    "extractor_args": {"youtube": {"player_client": ["web"]}},
}


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_video_id(video_id: str) -> None:
    vid = video_id.strip()
    if (
        not vid
        or len(vid) < 5
        or len(vid) > 16
        or not vid.replace("-", "").replace("_", "").isalnum()
    ):
        raise InvalidVideoIdError(f"Invalid videoId: '{video_id}'")


# ── Synchronous extraction (thread-pool) ─────────────────────────────────────

def _extract_sync(video_id: str) -> List[Dict[str, Any]]:
    """
    Run yt-dlp synchronously and return its raw format list.
    Called from a thread-pool executor so it never blocks the event loop.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Add 'yt-dlp' to requirements.txt."
        ) from exc

    source = settings.SOURCE_PLATFORM_URL.rstrip("/")
    url = f"{source}/watch?v={video_id}"
    log.info("[Resolver] Extracting formats for videoId=%s", video_id)

    with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
        try:
            info: Dict[str, Any] = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            log.error("[Resolver] yt-dlp DownloadError videoId=%s: %s", video_id, exc)
            raise InvidiousUpstreamError(0, str(exc)) from exc
        except Exception as exc:
            log.error("[Resolver] Unexpected extraction error videoId=%s: %s", video_id, exc)
            raise InvidiousUpstreamError(0, str(exc)) from exc

    formats: List[Dict[str, Any]] = info.get("formats") or []
    log.info("[Resolver] Extraction OK videoId=%s total_formats=%d", video_id, len(formats))
    return formats


# ── Public async API ──────────────────────────────────────────────────────────

async def resolve_m4a_url(video_id: str) -> ResolvedAudio:
    """
    Resolve the best audio-only M4A stream URL for *video_id*.

    Priority:
      1. itag 140 (128 kbps AAC M4A) — the gold standard for music.
      2. Any other audio-only M4A (highest bitrate wins).
      3. Any audio-only format in any container (last resort).

    Raises:
      InvalidVideoIdError    — malformed videoId
      NoAudioFormatsError    — yt-dlp returned no audio-only formats
      InvidiousUpstreamError — extraction failure
    """
    _validate_video_id(video_id)

    loop = asyncio.get_event_loop()
    all_formats = await loop.run_in_executor(
        None,
        functools.partial(_extract_sync, video_id),
    )

    if not all_formats:
        raise NoAudioFormatsError(f"yt-dlp returned no formats for videoId={video_id}")

    # ── Filter to audio-only ──────────────────────────────────────────────────
    audio_formats = [
        f for f in all_formats
        if (f.get("vcodec") or "none").lower() == "none"
        and f.get("acodec", "none").lower() != "none"
        and f.get("url")
    ]

    if not audio_formats:
        raise NoAudioFormatsError(
            f"No audio-only formats found for videoId={video_id}. "
            f"Total formats: {len(all_formats)}"
        )

    log.info(
        "[Resolver] videoId=%s audio_formats=%d (of %d total)",
        video_id, len(audio_formats), len(all_formats),
    )

    # ── Selection priority ────────────────────────────────────────────────────
    #  1.  itag 140
    itag_140 = [f for f in audio_formats if f.get("format_id") == str(_ITAG_M4A_128)]
    if itag_140:
        chosen = itag_140[0]
        log.info("[Resolver] itag 140 found — using it directly")
    else:
        #  2.  Best M4A by bitrate
        m4a_formats = [
            f for f in audio_formats
            if (f.get("ext") or "").lower() in ("m4a", "mp4")
        ]
        if m4a_formats:
            chosen = max(m4a_formats, key=lambda f: f.get("tbr") or f.get("abr") or 0)
            log.info("[Resolver] itag 140 absent — chose best M4A (format_id=%s)", chosen.get("format_id"))
        else:
            #  3.  Any audio
            chosen = max(audio_formats, key=lambda f: f.get("tbr") or f.get("abr") or 0)
            log.warning(
                "[Resolver] No M4A formats — fell back to format_id=%s ext=%s",
                chosen.get("format_id"), chosen.get("ext"),
            )

    # ── Build result ──────────────────────────────────────────────────────────
    ext = (chosen.get("ext") or "m4a").lower()
    tbr = chosen.get("tbr") or chosen.get("abr") or 0
    bitrate_bps = int(float(tbr) * 1000)

    # content-length is sometimes in filesize or filesize_approx
    clen: Optional[int] = chosen.get("filesize") or chosen.get("filesize_approx")
    if clen is not None:
        clen = int(clen)

    resolved = ResolvedAudio(
        video_id=video_id,
        stream_url=chosen["url"],
        mime_type=f"audio/{ext}" if ext != "mp4" else "audio/mp4",
        container=ext,
        bitrate=bitrate_bps,
        content_length=clen,
        itag=int(chosen.get("format_id", 0)) if str(chosen.get("format_id", "")).isdigit() else None,
    )

    log.info(
        "[Resolver] Resolved videoId=%s itag=%s mime=%s bitrate=%d clen=%s",
        video_id, resolved.itag, resolved.mime_type, resolved.bitrate, resolved.content_length,
    )
    return resolved


async def list_audio_formats(video_id: str) -> List[Dict[str, Any]]:
    """
    Return all audio-only formats for debug / /resolve/formats endpoint.
    """
    _validate_video_id(video_id)

    loop = asyncio.get_event_loop()
    all_formats = await loop.run_in_executor(
        None,
        functools.partial(_extract_sync, video_id),
    )
    return [
        {
            "format_id": f.get("format_id"),
            "ext":       f.get("ext"),
            "acodec":    f.get("acodec"),
            "abr":       f.get("abr"),
            "tbr":       f.get("tbr"),
            "filesize":  f.get("filesize"),
            "url":       f.get("url", "")[:120] + "…",   # truncate for readability
        }
        for f in all_formats
        if (f.get("vcodec") or "none").lower() == "none"
        and f.get("acodec", "none").lower() != "none"
        and f.get("url")
    ]
