"""
app/providers/youtube_ipv6_proxy/resolver.py
Resolves the itag-140 (.m4a, 128 kbps AAC) stream URL via pytubefix.

Extraction is fully self-contained on the server -- no external APIs.

Flow:
  1. Acquire PO tokens from Redis cache (or generate via Node.js CLI)
  2. Initialize pytubefix.YouTube with the tokens (no interactive prompt)
  3. Find the itag 140 stream (128 kbps AAC M4A)
  4. Read the ``.url`` property to get the direct googlevideo.com CDN URL
  5. Return the URL for the IPv6 streaming proxy to consume

The resolved URL is an *upstream CDN URL* -- callers must NOT expose
it to the client.  It is consumed internally by the streaming route
which proxies it through our IPv6 + UA rotation layer.

itag 140 spec:
  - Container : mp4 (M4A)
  - Codec     : mp4a.40.2 (AAC-LC)
  - Bitrate   : ~128 kbps
  - Seekable  : yes (single-segment, supports byte-range)
"""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.config import settings
from app.providers.youtube_ipv6_proxy.po_token_manager import po_token_manager, POToken
from app.utils.logging import get_logger
from app.utils.errors import (
    InvalidVideoIdError,
    NoAudioFormatsError,
    ProviderError,
)

log = get_logger(__name__)

# ── Target itag ───────────────────────────────────────────────────────────────
_ITAG_M4A_128 = 140   # 128 kbps AAC in MP4 container


@dataclass(frozen=True)
class ResolvedAudio:
    """Result of a successful audio URL resolution."""
    video_id:       str
    stream_url:     str             # direct CDN URL -- do NOT leak to client
    mime_type:      str             # "audio/mp4"
    container:      str             # "m4a"
    bitrate:        int             # bps
    content_length: Optional[int] = None   # bytes, if available
    itag:           Optional[int] = None


class ExtractionError(ProviderError):
    """pytubefix failed to extract stream data."""


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


# ── Synchronous extraction (runs in thread pool) ─────────────────────────────

def _extract_sync(video_id: str, token: POToken) -> ResolvedAudio:
    """
    Use pytubefix to resolve the direct CDN URL for itag 140.
    This is synchronous and MUST be called via ``run_in_executor``.
    """
    try:
        from pytubefix import YouTube
    except ImportError as exc:
        raise RuntimeError(
            "pytubefix is not installed. Add 'pytubefix' to requirements.txt."
        ) from exc

    url = f"{settings.SOURCE_PLATFORM_URL.rstrip('/')}/watch?v={video_id}"
    log.info("[Resolver] Initializing pytubefix for videoId=%s", video_id)

    try:
        yt = YouTube(
            url,
            use_po_token=True,
            po_token_verifier=(token.visitor_data, token.po_token),
        )
    except Exception as exc:
        log.error("[Resolver] pytubefix init failed for videoId=%s: %s", video_id, exc)
        raise ExtractionError(f"pytubefix failed to initialize: {exc}") from exc

    # ── List available streams for debug ──────────────────────────────────────
    try:
        all_streams = yt.streams
    except Exception as exc:
        log.error(
            "[Resolver] pytubefix stream listing failed for videoId=%s: %s",
            video_id, exc,
        )
        raise ExtractionError(f"Failed to list streams: {exc}") from exc

    log.info(
        "[Resolver] videoId=%s title='%s' total_streams=%d",
        video_id, getattr(yt, 'title', '?'), len(all_streams),
    )

    # ── Selection priority ────────────────────────────────────────────────────
    # 1. itag 140 (gold standard)
    stream = yt.streams.get_by_itag(_ITAG_M4A_128)

    if stream is not None:
        log.info("[Resolver] itag 140 found -- using it directly")
    else:
        # 2. Best audio-only (any format)
        stream = yt.streams.get_audio_only()
        if stream is not None:
            log.warning(
                "[Resolver] itag 140 absent -- fell back to audio_only "
                "(itag=%s mime=%s abr=%s)",
                stream.itag, stream.mime_type, getattr(stream, 'abr', '?'),
            )

    if stream is None:
        # 3. Log all streams for debug
        for i, s in enumerate(all_streams):
            log.debug("[Resolver] stream[%d]: %s", i, s)
        raise NoAudioFormatsError(
            f"No audio streams found for videoId={video_id}. "
            f"Total streams: {len(all_streams)}"
        )

    # ── Get the direct CDN URL (do NOT call .download()!) ─────────────────────
    try:
        direct_url = stream.url
    except Exception as exc:
        log.error("[Resolver] Failed to get stream URL for videoId=%s: %s", video_id, exc)
        raise ExtractionError(f"Failed to get stream URL: {exc}") from exc

    if not direct_url:
        raise ExtractionError(f"stream.url returned empty for videoId={video_id}")

    # ── Parse bitrate ─────────────────────────────────────────────────────────
    bitrate_bps = 0
    abr_raw = getattr(stream, 'abr', None)
    if abr_raw and isinstance(abr_raw, str):
        try:
            bitrate_bps = int(abr_raw.replace("kbps", "").strip()) * 1000
        except (ValueError, TypeError):
            bitrate_bps = 128000  # safe default for itag 140

    # ── Content length (avoid HEAD request; use approximate if available) ─────
    clen: Optional[int] = None
    try:
        clen = getattr(stream, 'filesize_approx', None)
        if clen is not None:
            clen = int(clen)
    except (ValueError, TypeError):
        pass

    # ── Build result ──────────────────────────────────────────────────────────
    mime = stream.mime_type or "audio/mp4"
    container = "m4a" if "mp4" in mime else stream.subtype or "m4a"

    resolved = ResolvedAudio(
        video_id=video_id,
        stream_url=direct_url,
        mime_type=mime,
        container=container,
        bitrate=bitrate_bps,
        content_length=clen,
        itag=stream.itag,
    )

    log.info(
        "[Resolver] Resolved videoId=%s itag=%s mime=%s bitrate=%d clen=%s url=%.80s...",
        video_id, resolved.itag, resolved.mime_type,
        resolved.bitrate, resolved.content_length, resolved.stream_url,
    )
    return resolved


# ── Public async API ──────────────────────────────────────────────────────────

async def resolve_m4a_url(video_id: str) -> ResolvedAudio:
    """
    Resolve the best audio-only M4A stream URL for *video_id*
    using pytubefix + PO tokens.

    Fully async -- pytubefix runs in a thread pool to avoid blocking
    the event loop.

    Raises:
      InvalidVideoIdError -- malformed videoId
      NoAudioFormatsError -- no audio-only formats found
      ExtractionError     -- pytubefix failure
      RuntimeError        -- PO token generation failure
    """
    _validate_video_id(video_id)

    # 1. Get PO tokens (from Redis cache or generate fresh)
    token = await po_token_manager.get_tokens()
    log.info(
        "[Resolver] Using PO tokens -- visitorData=%.30s... poToken=%.30s...",
        token.visitor_data, token.po_token,
    )

    # 2. Run pytubefix in thread pool (it does blocking HTTP)
    loop = asyncio.get_event_loop()
    try:
        resolved = await loop.run_in_executor(
            None,
            functools.partial(_extract_sync, video_id, token),
        )
    except (NoAudioFormatsError, InvalidVideoIdError):
        raise  # re-raise known errors directly
    except Exception as exc:
        log.error(
            "[Resolver] Extraction failed for videoId=%s: %s -- %s",
            video_id, type(exc).__name__, exc,
        )
        raise

    return resolved


async def list_audio_formats(video_id: str) -> List[Dict[str, Any]]:
    """
    Return all audio streams for debug / /resolve/formats endpoint.
    """
    _validate_video_id(video_id)

    token = await po_token_manager.get_tokens()

    def _list_sync() -> List[Dict[str, Any]]:
        from pytubefix import YouTube

        url = f"{settings.SOURCE_PLATFORM_URL.rstrip('/')}/watch?v={video_id}"
        yt = YouTube(
            url,
            use_po_token=True,
            po_token_verifier=(token.visitor_data, token.po_token),
        )

        results = []
        for s in yt.streams:
            if s.type == "audio":
                results.append({
                    "itag":      s.itag,
                    "mime_type": s.mime_type,
                    "abr":       getattr(s, 'abr', None),
                    "acodec":    getattr(s, 'audio_codec', None),
                    "filesize":  getattr(s, 'filesize_approx', None),
                    "url":       (s.url or "")[:120] + "...",
                })
        return results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list_sync)
