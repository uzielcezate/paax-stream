"""
app/services/invidious_service.py
Fetches video metadata from the Invidious API.

Endpoint used:
  GET {INVIDIOUS_BASE_URL}/api/v1/videos/{videoId}?local=true

The `local=true` parameter causes Invidious to rewrite stream URLs
to point at itself instead of googlevideo.com, which avoids
direct CDN dependency from the mobile client.
"""
import httpx
from typing import Any, Dict, List

from app.config import INVIDIOUS_BASE_URL, REQUEST_TIMEOUT_S, PROVIDER_NAME
from app.utils.logging import get_logger
from app.utils.errors import (
    InvidiousTimeoutError,
    InvidiousUpstreamError,
    NoAudioFormatsError,
    InvalidVideoIdError,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Headers sent with every Invidious request.
# Explicit browser-like set to avoid 401 / bot-blocks on the upstream.
# ---------------------------------------------------------------------------
_INVIDIOUS_HEADERS: Dict[str, str] = {
    "User-Agent":      "PaaxStream/1.0 (+https://paaxmusic.app; contact: support@paaxmusic.app)",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         f"{INVIDIOUS_BASE_URL}/",
    "Origin":          INVIDIOUS_BASE_URL,
    "Connection":      "keep-alive",
}

# Safe subset logged on every request (omit any credentials or tokens)
_LOGGED_HEADERS = ("User-Agent", "Accept", "Accept-Language", "Referer", "Origin")


def _validate_video_id(video_id: str) -> None:
    """Raise InvalidVideoIdError if videoId looks invalid."""
    vid = video_id.strip()
    if not vid or len(vid) < 5 or len(vid) > 16 or not vid.replace("-", "").replace("_", "").isalnum():
        raise InvalidVideoIdError(f"Invalid videoId: '{video_id}'")


async def fetch_audio_formats(video_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all audio-only adaptive formats for a video from Invidious.

    Returns a list of raw Invidious adaptiveFormat dicts where
    type starts with 'audio/'.

    Raises:
      InvalidVideoIdError     — bad videoId
      InvidiousTimeoutError   — request timed out
      InvidiousUpstreamError  — non-200 Invidious response
      NoAudioFormatsError     — valid video but zero audio formats
    """
    _validate_video_id(video_id)

    url = f"{INVIDIOUS_BASE_URL}/api/v1/videos/{video_id}?local=true"

    # Log request (safe headers only)
    safe_headers = {k: _INVIDIOUS_HEADERS[k] for k in _LOGGED_HEADERS if k in _INVIDIOUS_HEADERS}
    log.info("[Invidious] → GET %s", url)
    log.debug("[Invidious] Request headers: %s", safe_headers)

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_S,
            headers=_INVIDIOUS_HEADERS,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        log.error("[Invidious] Timeout fetching videoId=%s: %s", video_id, exc)
        raise InvidiousTimeoutError(f"Invidious timed out for {video_id}") from exc
    except httpx.RequestError as exc:
        log.error("[Invidious] Network error fetching videoId=%s: %s", video_id, exc)
        raise InvidiousUpstreamError(0, str(exc)) from exc

    content_type  = response.headers.get("content-type", "unknown")
    elapsed_ms    = response.elapsed.total_seconds() * 1000
    body_preview  = response.text[:300]

    log.info(
        "[Invidious] ← HTTP %d videoId=%s (%.0f ms) content-type=%s",
        response.status_code, video_id, elapsed_ms, content_type,
    )

    if response.status_code != 200:
        log.warning(
            "[Invidious] Non-200 for videoId=%s status=%d body_preview=%r",
            video_id, response.status_code, body_preview,
        )
        raise InvidiousUpstreamError(response.status_code, body_preview)

    # Guard: parse JSON only if the response actually claims to be JSON
    if "application/json" not in content_type and "text/json" not in content_type:
        log.error(
            "[Invidious] Unexpected content-type=%s for videoId=%s body_preview=%r",
            content_type, video_id, body_preview,
        )
        raise InvidiousUpstreamError(200, f"Non-JSON response ({content_type})")

    try:
        data: Dict[str, Any] = response.json()
    except Exception as exc:
        log.error(
            "[Invidious] JSON parse failed for videoId=%s body_preview=%r exc=%s",
            video_id, body_preview, exc,
        )
        raise InvidiousUpstreamError(200, "Invalid JSON") from exc

    adaptive_formats: List[Dict[str, Any]] = data.get("adaptiveFormats") or []

    audio_formats = [
        fmt for fmt in adaptive_formats
        if (fmt.get("type") or "").lower().startswith("audio/")
        and fmt.get("url")
    ]

    log.info(
        "[Invidious] videoId=%s: total_adaptive=%d audio_only=%d",
        video_id, len(adaptive_formats), len(audio_formats),
    )

    if not audio_formats:
        raise NoAudioFormatsError(
            f"No playable audio formats for videoId={video_id}"
        )

    return audio_formats


