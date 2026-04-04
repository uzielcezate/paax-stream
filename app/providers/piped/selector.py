"""
app/providers/piped/selector.py
Audio format ranking and selection logic for Piped audioStreams.

Piped's audioStreams fields:
  url, mimeType, format, bitrate, quality, codec (may be absent)

Selection priority (mirrors Invidious selector):
  TIER 1 — mimeType starts with "audio/mp4"   (AAC/M4A — widest compat)
  TIER 2 — mimeType starts with "audio/webm"  (Opus fallback)
  Sorted by bitrate descending within each tier.
  Entries with empty or missing url are ignored.
"""
from typing import Any, Dict, List, Optional

from app.providers.base import AudioFormat
from app.utils.logging import get_logger
from app.utils.errors import NoAudioFormatsError

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_mime(raw: str) -> str:
    """'audio/mp4;codecs=mp4a.40.2' → 'audio/mp4'"""
    return (raw or "").split(";")[0].strip().lower()


def _mime_to_container(mime: str) -> str:
    m = mime.lower()
    if "mp4" in m or "m4a" in m:
        return "mp4"
    if "webm" in m:
        return "webm"
    if "ogg" in m:
        return "ogg"
    return m.split("/")[-1].split(";")[0].strip() or "unknown"


def _bitrate(stream: Dict[str, Any]) -> int:
    """Piped uses 'bitrate' (int, bps). Fall back to 0 if absent."""
    return int(stream.get("bitrate") or 0)


def _is_usable(stream: Dict[str, Any]) -> bool:
    return bool(stream.get("url")) and bool(stream.get("mimeType"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_best(audio_streams: List[Dict[str, Any]]) -> AudioFormat:
    """
    Select the single best audio stream from Piped's audioStreams list.

    Returns an AudioFormat dataclass.
    Raises NoAudioFormatsError if no usable format can be found.
    """
    usable = [s for s in audio_streams if _is_usable(s)]

    mp4_streams  = [s for s in usable if _normalize_mime(s.get("mimeType", "")).startswith("audio/mp4")]
    webm_streams = [s for s in usable if _normalize_mime(s.get("mimeType", "")).startswith("audio/webm")]

    mp4_streams.sort(key=_bitrate, reverse=True)
    webm_streams.sort(key=_bitrate, reverse=True)

    chosen: Optional[Dict[str, Any]] = None
    tier: str = ""

    if mp4_streams:
        chosen = mp4_streams[0]
        tier   = "audio/mp4 (tier 1)"
    elif webm_streams:
        chosen = webm_streams[0]
        tier   = "audio/webm (tier 2 fallback)"
    else:
        raise NoAudioFormatsError(
            f"Piped: no usable mp4 or webm audio streams "
            f"(total_streams={len(audio_streams)} usable={len(usable)})"
        )

    mime      = _normalize_mime(chosen.get("mimeType", ""))
    container = _mime_to_container(chosen.get("mimeType", ""))
    bitrate   = _bitrate(chosen)

    log.info(
        "[Piped.selector] Chose %s bitrate=%d bps container=%s tier=%s",
        mime, bitrate, container, tier,
    )

    return AudioFormat(
        mime_type=mime,
        container=container,
        bitrate=bitrate,
        url=chosen["url"],
    )


def list_all(audio_streams: List[Dict[str, Any]]) -> List[AudioFormat]:
    """
    Return all usable audio streams normalised to AudioFormat.
    Sorted: mp4 first by bitrate desc, then webm by bitrate desc.
    """
    result: List[AudioFormat] = []
    for s in audio_streams:
        if not _is_usable(s):
            continue
        mime = _normalize_mime(s.get("mimeType", ""))
        result.append(AudioFormat(
            mime_type=mime,
            container=_mime_to_container(s.get("mimeType", "")),
            bitrate=_bitrate(s),
            url=s["url"],
        ))

    result.sort(key=lambda f: (
        0 if "mp4" in f.mime_type else 1,
        -f.bitrate,
    ))
    return result
