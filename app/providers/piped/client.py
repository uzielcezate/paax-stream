"""
app/providers/piped/client.py
Low-level HTTP client for the Piped API.

Endpoint:
  GET {instance_base_url}/streams/{videoId}

Responsibilities:
  - Try configured instances in order
  - Return raw JSON on first success
  - Raise a typed exception if all instances fail
  - Never send auth headers, cookies, or session data
  - Log which instance is tried and what status was returned
"""
import httpx
from typing import Any, Dict, List

from app.config import REQUEST_TIMEOUT_S
from app.providers.piped.instances import get_instances
from app.utils.logging import get_logger
from app.utils.errors import (
    InvidiousTimeoutError,    # reused as ProviderTimeoutError for now
    InvidiousUpstreamError,   # reused as ProviderUpstreamError for now
    InvalidVideoIdError,
    NoAudioFormatsError,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Minimal, stateless headers — NO auth, NO cookies, NO session
# ---------------------------------------------------------------------------
_HEADERS: Dict[str, str] = {
    "User-Agent":      "PaaxStream/1.0 (+https://paaxmusic.app; contact: support@paaxmusic.app)",
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
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


async def fetch_streams(video_id: str) -> Dict[str, Any]:
    """
    Try each Piped instance in order and return the first successful JSON response.

    Returns the raw dict from GET /streams/{videoId}.

    Raises:
      InvalidVideoIdError    — bad videoId
      InvidiousUpstreamError — all instances failed (status, body carried in last error)
      NoAudioFormatsError    — response has no audioStreams list
    """
    _validate_video_id(video_id)

    instances = get_instances()
    last_exc: Exception = RuntimeError("No Piped instances configured")

    for instance in instances:
        url = f"{instance}/streams/{video_id}"
        log.info("[Piped.client] → GET %s (instance=%s)", url, instance)

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_S,
                headers=_HEADERS,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)

        except httpx.TimeoutException as exc:
            log.warning("[Piped.client] Timeout on instance=%s videoId=%s", instance, video_id)
            last_exc = InvidiousTimeoutError(f"Piped instance {instance} timed out for {video_id}")
            continue
        except httpx.RequestError as exc:
            log.warning("[Piped.client] Network error instance=%s videoId=%s: %s", instance, video_id, exc)
            last_exc = InvidiousUpstreamError(0, str(exc))
            continue

        ct         = response.headers.get("content-type", "unknown")
        elapsed_ms = response.elapsed.total_seconds() * 1000
        preview    = response.text[:300]

        log.info(
            "[Piped.client] ← HTTP %d instance=%s videoId=%s (%.0f ms) content-type=%s",
            response.status_code, instance, video_id, elapsed_ms, ct,
        )

        if response.status_code != 200:
            log.warning(
                "[Piped.client] Non-200 instance=%s videoId=%s status=%d body=%r",
                instance, video_id, response.status_code, preview,
            )
            last_exc = InvidiousUpstreamError(response.status_code, preview)
            continue

        if "application/json" not in ct and "text/json" not in ct:
            log.warning(
                "[Piped.client] Non-JSON content-type=%s instance=%s videoId=%s body=%r",
                ct, instance, video_id, preview,
            )
            last_exc = InvidiousUpstreamError(200, f"Non-JSON response ({ct})")
            continue

        try:
            data: Dict[str, Any] = response.json()
        except Exception as exc:
            log.warning(
                "[Piped.client] JSON parse failed instance=%s videoId=%s body=%r exc=%s",
                instance, video_id, preview, exc,
            )
            last_exc = InvidiousUpstreamError(200, "Invalid JSON")
            continue

        audio_streams: List = data.get("audioStreams") or []
        log.info(
            "[Piped.client] OK instance=%s videoId=%s audioStreams=%d",
            instance, video_id, len(audio_streams),
        )

        if not audio_streams:
            log.warning("[Piped.client] No audioStreams for videoId=%s on instance=%s", video_id, instance)
            last_exc = NoAudioFormatsError(f"Piped: no audioStreams for videoId={video_id}")
            continue

        return data  # first successful response

    # All instances exhausted
    log.error(
        "[Piped.client] All %d instances failed for videoId=%s. Last error: %s",
        len(instances), video_id, last_exc,
    )
    raise last_exc
