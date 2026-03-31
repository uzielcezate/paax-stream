"""
app/services/stream_selector.py
Selects the single best audio format from a list of Invidious adaptiveFormats.

Selection strategy (mirrors Flutter mobile preference):

  TIER 1 — audio/mp4 (m4a / AAC)
    Most compatible: ExoPlayer, AVPlayer, just_audio all handle this natively.
    Sort: highest bitrate first.

  TIER 2 — audio/webm (opus)
    Fallback: ExoPlayer handles opus well, AVPlayer less so.
    Sort: highest bitrate first.

  If both tiers are empty → NoAudioFormatsError.
"""
from typing import Any, Dict, List, Optional

from app.utils.logging import get_logger
from app.utils.errors import NoAudioFormatsError

log = get_logger(__name__)


def _mime_to_container(mime: str) -> str:
    """Infer container string from a MIME type."""
    mime_lower = mime.lower()
    if "mp4" in mime_lower or "m4a" in mime_lower:
        return "mp4"
    if "webm" in mime_lower:
        return "webm"
    if "ogg" in mime_lower:
        return "ogg"
    return mime_lower.split("/")[-1].split(";")[0].strip()


def _normalize_mime(raw_type: str) -> str:
    """Strip codec params from MIME: 'audio/mp4; codecs="mp4a.40.2"' → 'audio/mp4'."""
    return raw_type.split(";")[0].strip().lower()


def _bitrate(fmt: Dict[str, Any]) -> int:
    """Return bitrate in bps, preferring 'bitrate' key, fallback to 'encoding'."""
    return int(fmt.get("bitrate") or fmt.get("encoding") or 0)


def select_best_audio(formats: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Pick the single best audio format.

    Returns a normalized dict:
      {
        "mimeType": "audio/mp4",
        "container": "mp4",
        "bitrate": 131550,
        "url": "https://..."
      }

    Raises NoAudioFormatsError if no usable format found.
    """
    mp4_formats  = []
    webm_formats = []

    for fmt in formats:
        raw_type = fmt.get("type") or ""
        mime     = _normalize_mime(raw_type)
        url      = fmt.get("url") or ""
        if not url:
            continue
        if "mp4" in mime or "m4a" in mime:
            mp4_formats.append(fmt)
        elif "webm" in mime or "opus" in mime:
            webm_formats.append(fmt)

    # Sort each tier by bitrate descending
    mp4_formats.sort(key=_bitrate, reverse=True)
    webm_formats.sort(key=_bitrate, reverse=True)

    chosen: Optional[Dict[str, Any]] = None
    if mp4_formats:
        chosen = mp4_formats[0]
        tier   = "audio/mp4 (tier 1)"
    elif webm_formats:
        chosen = webm_formats[0]
        tier   = "audio/webm (tier 2 fallback)"
    else:
        raise NoAudioFormatsError("No mp4 or webm audio formats available")

    raw_type  = chosen.get("type") or ""
    mime      = _normalize_mime(raw_type)
    container = _mime_to_container(raw_type)
    bitrate   = _bitrate(chosen)
    url       = chosen["url"]

    log.info(
        "[Selector] Chose %s — bitrate=%d bps container=%s tier=%s",
        mime, bitrate, container, tier,
    )

    return {
        "mimeType":  mime,
        "container": container,
        "bitrate":   bitrate,
        "url":       url,
    }


def list_audio_formats(formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize and return all audio formats for the debug endpoint.
    Sorted: mp4 first (by bitrate desc), then webm (by bitrate desc).
    """
    result = []
    for fmt in formats:
        raw_type  = fmt.get("type") or ""
        mime      = _normalize_mime(raw_type)
        container = _mime_to_container(raw_type)
        bitrate   = _bitrate(fmt)
        url       = fmt.get("url") or ""
        if not url:
            continue
        result.append({
            "mimeType":  mime,
            "container": container,
            "bitrate":   bitrate,
            "url":       url,
        })

    # mp4 first, then webm, each sorted by bitrate desc
    result.sort(key=lambda f: (
        0 if "mp4" in f["mimeType"] else 1,
        -f["bitrate"],
    ))
    return result
