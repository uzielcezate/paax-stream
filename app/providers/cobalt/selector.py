"""
app/providers/cobalt/selector.py
Normalises a Cobalt tunnel response into the internal AudioFormat / ResolvedStream shape.

Unlike Invidious/Piped (which return format arrays), Cobalt returns a single
pre-selected tunnel URL. This module handles that difference cleanly.

Design decisions:
  - mimeType is always "audio/mp4" (we request audioFormat=mp4)
  - bitrate is set to 128000 bps to match audioBitrate="128" in the request
  - resolve_formats() returns a single-element list (the tunnel URL) for API
    compatibility — this is a synthetic debug-friendly representation
"""
from typing import Any, Dict, List

from app.providers.base import AudioFormat
from app.utils.logging import get_logger
from app.utils.errors import NoAudioFormatsError

log = get_logger(__name__)

# Cobalt request constants (kept in sync with client.py payload)
_MIME_TYPE  = "audio/mp4"
_CONTAINER  = "mp4"
_BITRATE    = 128_000  # bps (matches audioBitrate="128" Kbps in request)


def normalize_stream(data: Dict[str, Any], video_id: str) -> AudioFormat:
    """
    Extract the tunnel URL from a Cobalt response and return a normalised AudioFormat.

    data must already be validated (status == "tunnel", url non-empty)
    by the client layer before calling this.
    """
    url = data.get("url", "")
    if not url:
        raise NoAudioFormatsError(f"Cobalt: empty tunnel URL for videoId={video_id}")

    log.info(
        "[Cobalt.selector] Normalised tunnel url_prefix=%s mimeType=%s bitrate=%d",
        url[:60], _MIME_TYPE, _BITRATE,
    )

    return AudioFormat(
        mime_type=_MIME_TYPE,
        container=_CONTAINER,
        bitrate=_BITRATE,
        url=url,
    )


def list_formats(data: Dict[str, Any], video_id: str) -> List[AudioFormat]:
    """
    Return a single-element list for the /resolve/formats debug endpoint.

    Cobalt is a single-stream resolver, so there is exactly one "format":
    the tunnel URL. This keeps the response schema consistent with other providers.
    """
    fmt = normalize_stream(data, video_id)
    return [fmt]
