"""
app/providers/youtube_local_mp4/selector.py
Format ranking and selection for youtube_local_mp4 provider.

Selection priority:
  TIER 1 — MP4 144p   (smallest, fastest, widest compat)
  TIER 2 — MP4 240p
  TIER 3 — MP4 360p
  TIER 4 — any other MP4 in ascending height order (last resort)

Excludes:
  - audio-only formats
  - WebM formats when a valid MP4 alternative exists
  - formats with no direct URL

Normalises chosen format into a VideoFormat / AudioFormat-compatible shape
that the provider and manager can serialise in the standard response contract.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.utils.logging import get_logger
from app.utils.errors import NoAudioFormatsError

log = get_logger(__name__)

# Height preference order for format selection
_PREFERRED_HEIGHTS = [144, 240, 360]

# Maximum height we allow in this provider
# (keeps bandwidth low and compatibility high)
_MAX_HEIGHT = 480


@dataclass
class VideoFormat:
    """Normalised output of a successful format selection."""
    url:       str
    mime_type: str   # "video/mp4"
    container: str   # "mp4"
    height:    int   # px
    width:     int   # px
    bitrate:   int   # bps (0 if unknown)
    format_id: str   # raw yt-dlp format_id for debugging


def _is_mp4_video(fmt: Dict[str, Any]) -> bool:
    """Return True if the format is a direct MP4 video stream (not audio-only)."""
    ext      = (fmt.get("ext") or "").lower()
    vcodec   = (fmt.get("vcodec") or "none").lower()
    acodec   = (fmt.get("acodec") or "").lower()  # may be "none" for video-only
    url      = fmt.get("url") or ""
    height   = fmt.get("height") or 0

    if not url:
        return False
    if ext != "mp4":
        return False
    if vcodec == "none" or not vcodec:
        return False  # audio-only or unknown
    if height <= 0:
        return False
    if height > _MAX_HEIGHT:
        return False  # skip anything above 480p

    return True


def _bitrate(fmt: Dict[str, Any]) -> int:
    tbr = fmt.get("tbr")
    vbr = fmt.get("vbr")
    abr = fmt.get("abr")
    val = tbr or vbr or abr or 0
    try:
        return int(float(val) * 1000)  # yt-dlp returns Kbps, convert to bps
    except (TypeError, ValueError):
        return 0


def select_best(formats: List[Dict[str, Any]]) -> VideoFormat:
    """
    Select the best low-resolution MP4 video format.

    Priority:
      1. 144p MP4
      2. 240p MP4
      3. 360p MP4
      4. Any MP4 below _MAX_HEIGHT (ascending height, ascending bitrate)

    Raises NoAudioFormatsError if no usable MP4 found.
    """
    candidates = [f for f in formats if _is_mp4_video(f)]

    log.info(
        "[YTLocalMP4.selector] Total formats=%d MP4-video candidates=%d",
        len(formats), len(candidates),
    )

    if not candidates:
        raise NoAudioFormatsError("youtube_local_mp4: no MP4 video formats available")

    # Build per-height buckets
    by_height: Dict[int, List[Dict[str, Any]]] = {}
    for fmt in candidates:
        h = fmt.get("height") or 0
        by_height.setdefault(h, []).append(fmt)

    # 1. Try preferred heights in order
    for target_h in _PREFERRED_HEIGHTS:
        bucket = by_height.get(target_h)
        if bucket:
            # Within height bucket: highest bitrate (better quality within same res)
            chosen = max(bucket, key=_bitrate)
            log.info(
                "[YTLocalMP4.selector] Chose preferred height=%dp format_id=%s bitrate=%d",
                target_h, chosen.get("format_id"), _bitrate(chosen),
            )
            return _normalise(chosen)

    # 2. Fallback: pick the lowest available MP4 height below MAX
    chosen = min(candidates, key=lambda f: (f.get("height") or 9999, -_bitrate(f)))
    log.info(
        "[YTLocalMP4.selector] Fallback: chose height=%dp format_id=%s bitrate=%d",
        chosen.get("height"), chosen.get("format_id"), _bitrate(chosen),
    )
    return _normalise(chosen)


def list_candidates(formats: List[Dict[str, Any]]) -> List[VideoFormat]:
    """
    Return all MP4 video candidates sorted by preferred height then bitrate.
    Used by /resolve/formats debug endpoint.
    """
    candidates = [f for f in formats if _is_mp4_video(f)]

    result = [_normalise(f) for f in candidates]
    result.sort(key=lambda v: (
        _height_rank(v.height),
        -v.bitrate,
    ))
    return result


def _height_rank(height: int) -> int:
    """Lower rank = preferred. Preferred heights get priority slots."""
    try:
        return _PREFERRED_HEIGHTS.index(height)
    except ValueError:
        return len(_PREFERRED_HEIGHTS) + height


def _normalise(fmt: Dict[str, Any]) -> VideoFormat:
    height = fmt.get("height") or 0
    width  = fmt.get("width")  or 0
    return VideoFormat(
        url=fmt["url"],
        mime_type="video/mp4",
        container="mp4",
        height=height,
        width=width,
        bitrate=_bitrate(fmt),
        format_id=fmt.get("format_id", "unknown"),
    )
