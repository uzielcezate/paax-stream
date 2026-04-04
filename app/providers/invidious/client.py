"""
app/providers/invidious/client.py
Low-level HTTP client for the Invidious API.

Responsible ONLY for:
  - Sending requests to Invidious with correct headers
  - Returning raw JSON as a Python dict
  - Raising typed exceptions on failure

Does NOT select formats or apply business logic.
"""
import httpx
from typing import Any, Dict

from app.config import INVIDIOUS_BASE_URL, REQUEST_TIMEOUT_S
from app.utils.logging import get_logger
from app.utils.errors import (
    InvidiousTimeoutError,
    InvidiousUpstreamError,
    InvalidVideoIdError,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Headers sent with every Invidious request.
# Explicit browser-like set to avoid 401 / bot-blocks on the upstream.
# ---------------------------------------------------------------------------
_HEADERS: Dict[str, str] = {
    "User-Agent":      "PaaxStream/1.0 (+https://paaxmusic.app; contact: support@paaxmusic.app)",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         f"{INVIDIOUS_BASE_URL}/",
    "Origin":          INVIDIOUS_BASE_URL,
    "Connection":      "keep-alive",
}

_LOGGED_HEADERS = ("User-Agent", "Accept", "Accept-Language", "Referer", "Origin")


def validate_video_id(video_id: str) -> None:
    """Raise InvalidVideoIdError if videoId is malformed."""
    vid = video_id.strip()
    if (
        not vid
        or len(vid) < 5
        or len(vid) > 16
        or not vid.replace("-", "").replace("_", "").isalnum()
    ):
        raise InvalidVideoIdError(f"Invalid videoId: '{video_id}'")


async def fetch_video_info(video_id: str) -> Dict[str, Any]:
    """
    GET /api/v1/videos/{videoId}?local=true from Invidious.

    Returns the full parsed JSON response dict.

    Raises:
      InvalidVideoIdError    — bad videoId
      InvidiousTimeoutError  — request timed out
      InvidiousUpstreamError — non-200 or non-JSON response
    """
    validate_video_id(video_id)

    url = f"{INVIDIOUS_BASE_URL}/api/v1/videos/{video_id}?local=true"

    safe_hdrs = {k: _HEADERS[k] for k in _LOGGED_HEADERS if k in _HEADERS}
    log.info("[Invidious.client] → GET %s", url)
    log.debug("[Invidious.client] Headers: %s", safe_hdrs)

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_S,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        log.error("[Invidious.client] Timeout videoId=%s: %s", video_id, exc)
        raise InvidiousTimeoutError(f"Invidious timed out for {video_id}") from exc
    except httpx.RequestError as exc:
        log.error("[Invidious.client] Network error videoId=%s: %s", video_id, exc)
        raise InvidiousUpstreamError(0, str(exc)) from exc

    ct         = response.headers.get("content-type", "unknown")
    elapsed_ms = response.elapsed.total_seconds() * 1000
    preview    = response.text[:300]

    log.info(
        "[Invidious.client] ← HTTP %d videoId=%s (%.0f ms) content-type=%s",
        response.status_code, video_id, elapsed_ms, ct,
    )

    if response.status_code != 200:
        log.warning(
            "[Invidious.client] Non-200 videoId=%s status=%d body=%r",
            video_id, response.status_code, preview,
        )
        raise InvidiousUpstreamError(response.status_code, preview)

    if "application/json" not in ct and "text/json" not in ct:
        log.error(
            "[Invidious.client] Unexpected content-type=%s videoId=%s body=%r",
            ct, video_id, preview,
        )
        raise InvidiousUpstreamError(200, f"Non-JSON response ({ct})")

    try:
        return response.json()
    except Exception as exc:
        log.error(
            "[Invidious.client] JSON parse failed videoId=%s body=%r exc=%s",
            video_id, preview, exc,
        )
        raise InvidiousUpstreamError(200, "Invalid JSON") from exc
