"""
app/routes/resolve.py
Stream resolution endpoints for paax-stream.

GET /resolve/stream/{videoId}
  → best playable audio URL (used by Flutter client for playback)

GET /resolve/formats/{videoId}
  → all detected audio formats (debug / inspection)
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import PROVIDER_NAME
from app.models import StreamResponse, FormatsResponse, AudioFormat, CacheInfo
from app.services.invidious_service import fetch_audio_formats
from app.services.stream_selector import select_best_audio, list_audio_formats
from app.services.cache_service import stream_cache
from app.utils.logging import get_logger
from app.utils.errors import (
    stream_error,
    InvidiousTimeoutError,
    InvidiousUpstreamError,
    NoAudioFormatsError,
    InvalidVideoIdError,
)

log    = get_logger(__name__)
router = APIRouter(prefix="/resolve")


# ---------------------------------------------------------------------------
# GET /resolve/stream/{videoId}
# ---------------------------------------------------------------------------

@router.get(
    "/stream/{videoId}",
    summary="Resolve best audio stream URL",
    response_model=StreamResponse,
)
async def resolve_stream(videoId: str) -> JSONResponse:
    """
    Resolve the single best playable audio stream URL for a YouTube videoId
    via Invidious (?local=true).

    Caches successful results in memory for CACHE_TTL_SECONDS.
    Does not cache failures.

    Response shape:
      { success, videoId, provider, streamUrl, mimeType, container, bitrate, cache }
    """
    video_id = videoId.strip()
    log.info("[resolve/stream] → videoId=%s", video_id)

    # ── 1. Cache check ─────────────────────────────────────────────────────────
    cached = stream_cache.get(video_id)
    if cached is not None:
        log.info("[resolve/stream] Cache HIT for videoId=%s", video_id)
        return JSONResponse(content={**cached, "cache": {"hit": True, "layer": "memory"}})

    # ── 2. Fetch from Invidious ─────────────────────────────────────────────────
    try:
        raw_formats = await fetch_audio_formats(video_id)
    except InvalidVideoIdError as exc:
        log.warning("[resolve/stream] Invalid videoId=%s: %s", video_id, exc)
        return stream_error(video_id, "INVALID_VIDEO_ID", str(exc), http_status=400)
    except InvidiousTimeoutError as exc:
        log.error("[resolve/stream] Timeout for videoId=%s", video_id)
        return stream_error(video_id, "PROVIDER_TIMEOUT",
                            "Invidious request timed out", http_status=504)
    except InvidiousUpstreamError as exc:
        log.error("[resolve/stream] Upstream error HTTP %d for videoId=%s",
                  exc.status_code, video_id)
        return stream_error(
            video_id, "PROVIDER_ERROR",
            f"Invidious returned HTTP {exc.status_code}",
            http_status=502,
        )
    except NoAudioFormatsError as exc:
        log.warning("[resolve/stream] No audio formats for videoId=%s", video_id)
        return stream_error(video_id, "NO_AUDIO_FORMATS", str(exc), http_status=422)

    # ── 3. Select best format ──────────────────────────────────────────────────
    try:
        best = select_best_audio(raw_formats)
    except NoAudioFormatsError as exc:
        return stream_error(video_id, "NO_AUDIO_FORMATS", str(exc), http_status=422)

    # ── 4. Build response + prime cache ───────────────────────────────────────
    payload = {
        "success":   True,
        "videoId":   video_id,
        "provider":  PROVIDER_NAME,
        "streamUrl": best["url"],
        "mimeType":  best["mimeType"],
        "container": best["container"],
        "bitrate":   best["bitrate"],
    }
    stream_cache.set(video_id, payload)

    log.info(
        "[resolve/stream] OK videoId=%s mimeType=%s bitrate=%d provider=%s",
        video_id, best["mimeType"], best["bitrate"], PROVIDER_NAME,
    )

    return JSONResponse(content={**payload, "cache": {"hit": False, "layer": "provider"}})


# ---------------------------------------------------------------------------
# GET /resolve/formats/{videoId}
# ---------------------------------------------------------------------------

@router.get(
    "/formats/{videoId}",
    summary="List all detected audio formats (debug)",
    response_model=FormatsResponse,
)
async def resolve_formats(videoId: str) -> JSONResponse:
    """
    Returns all audio-only formats for a videoId.
    Sorted: mp4/m4a first (by bitrate desc), then webm/opus.
    Intended for debugging — not called by the Flutter client in production.
    """
    video_id = videoId.strip()
    log.info("[resolve/formats] → videoId=%s", video_id)

    try:
        raw_formats = await fetch_audio_formats(video_id)
    except InvalidVideoIdError as exc:
        return stream_error(video_id, "INVALID_VIDEO_ID", str(exc), http_status=400)
    except InvidiousTimeoutError:
        return stream_error(video_id, "PROVIDER_TIMEOUT",
                            "Invidious request timed out", http_status=504)
    except InvidiousUpstreamError as exc:
        return stream_error(video_id, "PROVIDER_ERROR",
                            f"Invidious returned HTTP {exc.status_code}",
                            http_status=502)
    except NoAudioFormatsError as exc:
        return stream_error(video_id, "NO_AUDIO_FORMATS", str(exc), http_status=422)

    normalized = list_audio_formats(raw_formats)

    log.info("[resolve/formats] videoId=%s found %d formats", video_id, len(normalized))

    return JSONResponse(content={
        "success":  True,
        "videoId":  video_id,
        "provider": PROVIDER_NAME,
        "formats":  normalized,
    })
