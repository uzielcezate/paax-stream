"""
app/providers/youtube_ipv6_proxy/resolver.py
Resolves the itag-140 (.m4a, 128 kbps AAC) stream URL via Invidious API.

Instead of running yt-dlp locally (which requires PO tokens / login to
bypass bot detection), we query a federated Invidious instance's public
API to obtain the direct CDN URL for itag 140.

Flow:
  1. GET {INVIDIOUS_BASE_URL}/api/v1/videos/{video_id}
  2. Parse the JSON response -> adaptiveFormats[]
  3. Find the entry where itag == "140" (128 kbps AAC M4A)
  4. Return the direct googlevideo.com CDN URL

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

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utils.logging import get_logger
from app.utils.errors import (
    InvalidVideoIdError,
    NoAudioFormatsError,
    InvidiousUpstreamError,
    InvidiousTimeoutError,
)

log = get_logger(__name__)

# ── Target itag ───────────────────────────────────────────────────────────────
_ITAG_M4A_128 = "140"   # Invidious returns itag as a string


@dataclass(frozen=True)
class ResolvedAudio:
    """Result of a successful audio URL resolution."""
    video_id:       str
    stream_url:     str             # direct CDN URL -- do NOT leak to client
    mime_type:      str             # "audio/mp4"
    container:      str             # "m4a"
    bitrate:        int             # bps
    content_length: Optional[int] = None   # bytes, if reported by Invidious
    itag:           Optional[int] = None


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


# ── Invidious API client ─────────────────────────────────────────────────────

async def _fetch_invidious(video_id: str) -> Dict[str, Any]:
    """
    Query the Invidious API for video metadata.

    Returns the full JSON response dict containing adaptiveFormats, etc.

    Raises:
      InvidiousTimeoutError  -- request timed out
      InvidiousUpstreamError -- non-200 response from Invidious
    """
    base_url = settings.INVIDIOUS_BASE_URL.rstrip("/")
    api_url = f"{base_url}/api/v1/videos/{video_id}"

    log.info("[Resolver] Querying Invidious: %s", api_url)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_s),
        follow_redirects=True,
    ) as client:
        try:
            resp = await client.get(
                api_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                },
            )
        except httpx.TimeoutException as exc:
            log.error("[Resolver] Invidious timeout for videoId=%s: %s", video_id, exc)
            raise InvidiousTimeoutError(f"Invidious request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            log.error("[Resolver] Invidious HTTP error for videoId=%s: %s", video_id, exc)
            raise InvidiousUpstreamError(0, str(exc)) from exc

    if resp.status_code != 200:
        body = resp.text[:500]
        log.error(
            "[Resolver] Invidious returned HTTP %d for videoId=%s: %s",
            resp.status_code, video_id, body,
        )
        raise InvidiousUpstreamError(resp.status_code, body)

    data: Dict[str, Any] = resp.json()
    log.info(
        "[Resolver] Invidious OK for videoId=%s (title=%.50s...)",
        video_id, data.get("title", "?"),
    )
    return data


# ── Format extraction helpers ────────────────────────────────────────────────

def _normalize_mime(raw: str) -> str:
    """'audio/mp4; codecs=\"mp4a.40.2\"' -> 'audio/mp4'"""
    return raw.split(";")[0].strip().lower()


def _extract_adaptive_formats(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pull the adaptiveFormats array from the Invidious response.
    Filter to audio-only entries that have a direct URL.
    """
    adaptive = data.get("adaptiveFormats") or []
    audio_formats = [
        f for f in adaptive
        if f.get("type", "").startswith("audio/")
        and f.get("url")
    ]
    return audio_formats


# ── Public async API ──────────────────────────────────────────────────────────

async def resolve_m4a_url(video_id: str) -> ResolvedAudio:
    """
    Resolve the best audio-only M4A stream URL for *video_id*
    via the Invidious API.

    Priority:
      1. itag 140 (128 kbps AAC M4A) -- the gold standard for music.
      2. Any other audio/mp4 format (highest bitrate wins).
      3. Any audio format in any container (last resort).

    Raises:
      InvalidVideoIdError    -- malformed videoId
      NoAudioFormatsError    -- no audio-only formats found
      InvidiousUpstreamError -- Invidious API error
      InvidiousTimeoutError  -- Invidious request timed out
    """
    _validate_video_id(video_id)

    data = await _fetch_invidious(video_id)
    audio_formats = _extract_adaptive_formats(data)

    if not audio_formats:
        raise NoAudioFormatsError(
            f"No audio-only formats found for videoId={video_id}. "
            f"adaptiveFormats count: {len(data.get('adaptiveFormats', []))}"
        )

    log.info(
        "[Resolver] videoId=%s audio_formats=%d",
        video_id, len(audio_formats),
    )

    # ── Selection priority ────────────────────────────────────────────────────
    chosen: Optional[Dict[str, Any]] = None

    #  1.  itag 140
    for f in audio_formats:
        if str(f.get("itag")) == _ITAG_M4A_128:
            chosen = f
            log.info("[Resolver] itag 140 found -- using it directly")
            break

    if chosen is None:
        #  2.  Best audio/mp4 by bitrate
        mp4_formats = [
            f for f in audio_formats
            if "mp4" in _normalize_mime(f.get("type", ""))
        ]
        if mp4_formats:
            chosen = max(mp4_formats, key=lambda f: int(f.get("bitrate", 0)))
            log.info(
                "[Resolver] itag 140 absent -- chose best audio/mp4 (itag=%s)",
                chosen.get("itag"),
            )

    if chosen is None:
        #  3.  Any audio format
        chosen = max(audio_formats, key=lambda f: int(f.get("bitrate", 0)))
        log.warning(
            "[Resolver] No audio/mp4 -- fell back to itag=%s type=%s",
            chosen.get("itag"), chosen.get("type"),
        )

    # ── Build result ──────────────────────────────────────────────────────────
    raw_type = chosen.get("type", "audio/mp4")
    mime = _normalize_mime(raw_type)
    container = "m4a" if "mp4" in mime else mime.split("/")[-1]
    bitrate = int(chosen.get("bitrate", 0))

    # Invidious often provides clen (content-length)
    clen: Optional[int] = None
    clen_raw = chosen.get("clen") or chosen.get("contentLength")
    if clen_raw is not None:
        try:
            clen = int(clen_raw)
        except (ValueError, TypeError):
            pass

    itag_val: Optional[int] = None
    try:
        itag_val = int(chosen.get("itag", 0))
    except (ValueError, TypeError):
        pass

    resolved = ResolvedAudio(
        video_id=video_id,
        stream_url=chosen["url"],
        mime_type=mime,
        container=container,
        bitrate=bitrate,
        content_length=clen,
        itag=itag_val,
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

    data = await _fetch_invidious(video_id)
    audio_formats = _extract_adaptive_formats(data)

    return [
        {
            "itag":      f.get("itag"),
            "type":      f.get("type"),
            "bitrate":   f.get("bitrate"),
            "clen":      f.get("clen") or f.get("contentLength"),
            "container": f.get("container"),
            "url":       (f.get("url", ""))[:120] + "...",  # truncate for readability
        }
        for f in audio_formats
    ]
