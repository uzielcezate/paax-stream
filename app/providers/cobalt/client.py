"""
app/providers/cobalt/client.py
Low-level HTTP client for the Cobalt API.

Cobalt is a POST-based stream resolver:
  POST {instance_url}
  Headers: Accept: application/json, Content-Type: application/json
  Body:    see _build_payload()

On success, Cobalt returns:
  { "status": "tunnel", "url": "<tunnel_url>", "filename": "..." }

The "url" field is the playable tunnel URL proxied through Cobalt.

Responsibilities:
  - Try configured instances in order until one succeeds
  - Validate the response (status == "tunnel", url non-empty)
  - Raise typed exceptions on failure
  - Never mix provider logic here — just raw HTTP + response validation
"""
import httpx
from typing import Any, Dict

from app.config import REQUEST_TIMEOUT_S
from app.providers.cobalt.instances import get_instances
from app.utils.logging import get_logger
from app.utils.errors import (
    InvidiousTimeoutError,
    InvidiousUpstreamError,
    NoAudioFormatsError,
    InvalidVideoIdError,
)

log = get_logger(__name__)

_HEADERS: Dict[str, str] = {
    "Accept":       "application/json",
    "Content-Type": "application/json",
    "User-Agent":   "PaaxStream/1.0 (+https://paaxmusic.app; contact: support@paaxmusic.app)",
}

# Cobalt audio format preference — mp4 = AAC, widest player compat
_AUDIO_FORMAT   = "mp4"
_AUDIO_BITRATE  = "128"


def _validate_video_id(video_id: str) -> None:
    vid = video_id.strip()
    if (
        not vid
        or len(vid) < 5
        or len(vid) > 16
        or not vid.replace("-", "").replace("_", "").isalnum()
    ):
        raise InvalidVideoIdError(f"Invalid videoId: '{video_id}'")


def _build_payload(video_id: str) -> Dict[str, Any]:
    """Build the JSON POST body for a Cobalt stream request."""
    return {
        "url":             f"https://www.youtube.com/watch?v={video_id}",
        "downloadMode":    "audio",
        "audioFormat":     _AUDIO_FORMAT,
        "audioBitrate":    _AUDIO_BITRATE,
        "alwaysProxy":     True,
        "disableMetadata": True,
    }


async def fetch_tunnel(video_id: str) -> Dict[str, Any]:
    """
    POST to each Cobalt instance in order until one returns a valid tunnel response.

    Returns the parsed JSON dict:
      { "status": "tunnel", "url": "...", "filename": "..." }

    Raises:
      InvalidVideoIdError    — bad videoId
      InvidiousUpstreamError — all instances failed or returned invalid data
      NoAudioFormatsError    — response lacks a usable url
    """
    _validate_video_id(video_id)

    instances = get_instances()
    payload   = _build_payload(video_id)
    last_exc: Exception = RuntimeError("No Cobalt instances configured")

    for instance in instances:
        log.info("[Cobalt.client] → POST %s videoId=%s", instance, video_id)

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_S,
                headers=_HEADERS,
                follow_redirects=True,
            ) as client:
                response = await client.post(instance, json=payload)

        except httpx.TimeoutException as exc:
            log.warning("[Cobalt.client] Timeout instance=%s videoId=%s", instance, video_id)
            last_exc = InvidiousTimeoutError(f"Cobalt instance {instance} timed out for {video_id}")
            continue
        except httpx.RequestError as exc:
            log.warning("[Cobalt.client] Network error instance=%s videoId=%s: %s", instance, video_id, exc)
            last_exc = InvidiousUpstreamError(0, str(exc))
            continue

        ct         = response.headers.get("content-type", "unknown")
        elapsed_ms = response.elapsed.total_seconds() * 1000
        preview    = response.text[:300]

        log.info(
            "[Cobalt.client] ← HTTP %d instance=%s videoId=%s (%.0f ms) content-type=%s",
            response.status_code, instance, video_id, elapsed_ms, ct,
        )

        if response.status_code != 200:
            log.warning(
                "[Cobalt.client] Non-200 instance=%s status=%d body=%r",
                instance, response.status_code, preview,
            )
            last_exc = InvidiousUpstreamError(response.status_code, preview)
            continue

        if "application/json" not in ct and "text/json" not in ct:
            log.warning(
                "[Cobalt.client] Non-JSON content-type=%s instance=%s body=%r",
                ct, instance, preview,
            )
            last_exc = InvidiousUpstreamError(200, f"Non-JSON response ({ct})")
            continue

        try:
            data: Dict[str, Any] = response.json()
        except Exception as exc:
            log.warning(
                "[Cobalt.client] JSON parse failed instance=%s body=%r exc=%s",
                instance, preview, exc,
            )
            last_exc = InvidiousUpstreamError(200, "Invalid JSON")
            continue

        status = data.get("status", "")
        url    = data.get("url", "")

        if status != "tunnel":
            log.warning(
                "[Cobalt.client] Unexpected status=%r instance=%s videoId=%s body=%r",
                status, instance, video_id, preview,
            )
            last_exc = InvidiousUpstreamError(200, f"Cobalt status={status!r} (expected 'tunnel')")
            continue

        if not url:
            log.warning(
                "[Cobalt.client] Empty tunnel URL from instance=%s videoId=%s",
                instance, video_id,
            )
            last_exc = NoAudioFormatsError(f"Cobalt returned empty tunnel URL for videoId={video_id}")
            continue

        log.info(
            "[Cobalt.client] Tunnel OK instance=%s videoId=%s url_prefix=%s",
            instance, video_id, url[:60],
        )
        return data  # success

    # All instances exhausted
    log.error(
        "[Cobalt.client] All %d instances failed for videoId=%s. Last: %s",
        len(instances), video_id, last_exc,
    )
    raise last_exc
