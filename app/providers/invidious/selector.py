"""
app/providers/invidious/selector.py
Audio format ranking and selection logic for Invidious adaptiveFormats.

Moved from services/stream_selector.py — logic is unchanged.
This module is pure (no I/O) and easy to unit-test.

Selection strategy:
  TIER 1 — audio/mp4 / m4a (AAC)  — widest ExoPlayer + AVPlayer compat
  TIER 2 — audio/webm / opus       — fallback
  Sorted by bitrate descending within each tier.
"""
from typing import Any, Dict, List, Optional

from app.providers.base import AudioFormat
from app.utils.logging import get_logger
from app.utils.errors import NoAudioFormatsError

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_mime(raw_type: str) -> str:
    """'audio/mp4; codecs="mp4a.40.2"' → 'audio/mp4'"""
    return raw_type.split(";")[0].strip().lower()


def _mime_to_container(mime: str) -> str:
    m = mime.lower()
    if "mp4" in m or "m4a" in m:
        return "mp4"
    if "webm" in m:
        return "webm"
    if "ogg" in m:
        return "ogg"
    return m.split("/")[-1].split(";")[0].strip()


def _bitrate(fmt: Dict[str, Any]) -> int:
    return int(fmt.get("bitrate") or fmt.get("encoding") or 0)


def _is_audio(fmt: Dict[str, Any]) -> bool:
    return (fmt.get("type") or "").lower().startswith("audio/") and bool(fmt.get("url"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_best(raw_formats: List[Dict[str, Any]]) -> AudioFormat:
    """
    Select the single best audio format from a list of Invidious adaptiveFormats.

    Returns an AudioFormat dataclass.
    Raises NoAudioFormatsError if no usable format exists.
    """
    audio = [f for f in raw_formats if _is_audio(f)]

    mp4_fmts  = [f for f in audio if "mp4" in _normalize_mime(f.get("type", "")) or "m4a" in _normalize_mime(f.get("type", ""))]
    webm_fmts = [f for f in audio if "webm" in _normalize_mime(f.get("type", "")) or "opus" in _normalize_mime(f.get("type", ""))]

    mp4_fmts.sort(key=_bitrate, reverse=True)
    webm_fmts.sort(key=_bitrate, reverse=True)

    if mp4_fmts:
        chosen = mp4_fmts[0]
        tier   = "audio/mp4 (tier 1)"
    elif webm_fmts:
        chosen = webm_fmts[0]
        tier   = "audio/webm (tier 2 fallback)"
    else:
        raise NoAudioFormatsError("No mp4 or webm audio formats available")

    raw_type  = chosen.get("type") or ""
    mime      = _normalize_mime(raw_type)
    container = _mime_to_container(raw_type)
    bitrate   = _bitrate(chosen)

    log.info(
        "[Invidious.selector] Chose %s bitrate=%d bps container=%s tier=%s",
        mime, bitrate, container, tier,
    )

    return AudioFormat(
        mime_type=mime,
        container=container,
        bitrate=bitrate,
        url=chosen["url"],
    )


def list_all(raw_formats: List[Dict[str, Any]]) -> List[AudioFormat]:
    """
    Return all audio formats normalised to AudioFormat.
    Sorted: mp4 first by bitrate desc, then webm by bitrate desc.
    """
    result: List[AudioFormat] = []
    for fmt in raw_formats:
        if not _is_audio(fmt):
            continue
        raw_type = fmt.get("type") or ""
        result.append(AudioFormat(
            mime_type=_normalize_mime(raw_type),
            container=_mime_to_container(raw_type),
            bitrate=_bitrate(fmt),
            url=fmt["url"],
        ))

    result.sort(key=lambda f: (
        0 if "mp4" in f.mime_type else 1,
        -f.bitrate,
    ))
    return result
