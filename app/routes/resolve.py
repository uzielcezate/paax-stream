"""
app/routes/resolve.py
Stream resolution endpoints for paax-stream.

Routes delegate ALL resolution logic to provider_manager.
They never import Invidious classes or other provider internals directly.

GET /resolve/stream/{videoId}  → best playable audio URL
GET /resolve/formats/{videoId} → all audio formats (debug)
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.resolver.provider_manager import provider_manager
from app.models import StreamResponse, FormatsResponse
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
    Resolve the single best playable audio stream URL for a YouTube videoId.

    Internally delegates to provider_manager → InvidiousProvider.
    Caches successful results in memory for CACHE_TTL_SECONDS.
    Does not cache failures.

    Response: { success, videoId, provider, streamUrl, mimeType, container, bitrate, cache }
    """
    video_id = videoId.strip()
    log.info("[resolve/stream] → videoId=%s", video_id)

    try:
        result = await provider_manager.resolve_stream(video_id)
        log.info(
            "[resolve/stream] OK videoId=%s mimeType=%s bitrate=%d provider=%s cached=%s",
            video_id,
            result.get("mimeType"),
            result.get("bitrate", 0),
            result.get("provider"),
            result.get("cache", {}).get("hit"),
        )
        return JSONResponse(content=result)

    except InvalidVideoIdError as exc:
        log.warning("[resolve/stream] Invalid videoId=%s: %s", video_id, exc)
        return stream_error(video_id, "INVALID_VIDEO_ID", str(exc), http_status=400)

    except InvidiousTimeoutError:
        log.error("[resolve/stream] Timeout for videoId=%s", video_id)
        return stream_error(video_id, "PROVIDER_TIMEOUT",
                            "Provider request timed out", http_status=504)

    except InvidiousUpstreamError as exc:
        log.error("[resolve/stream] Upstream error HTTP %d videoId=%s",
                  exc.status_code, video_id)
        return stream_error(
            video_id, "PROVIDER_ERROR",
            f"Provider returned HTTP {exc.status_code}",
            http_status=502,
        )

    except NoAudioFormatsError as exc:
        log.warning("[resolve/stream] No audio formats videoId=%s", video_id)
        return stream_error(video_id, "NO_AUDIO_FORMATS", str(exc), http_status=422)

    except Exception as exc:
        log.error("[resolve/stream] Unexpected error videoId=%s: %s", video_id, exc)
        return stream_error(video_id, "INTERNAL_ERROR",
                            "Unexpected resolver error", http_status=500)


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
    Returns all audio-only formats for a videoId via the primary provider.
    Sorted: mp4/m4a first by bitrate desc, then webm/opus.
    Intended for debugging — not called by the Flutter client in production.
    """
    video_id = videoId.strip()
    log.info("[resolve/formats] → videoId=%s", video_id)

    try:
        result = await provider_manager.resolve_formats(video_id)
        log.info("[resolve/formats] OK videoId=%s formats=%d",
                 video_id, len(result.get("formats", [])))
        return JSONResponse(content=result)

    except InvalidVideoIdError as exc:
        return stream_error(video_id, "INVALID_VIDEO_ID", str(exc), http_status=400)

    except InvidiousTimeoutError:
        return stream_error(video_id, "PROVIDER_TIMEOUT",
                            "Provider request timed out", http_status=504)

    except InvidiousUpstreamError as exc:
        return stream_error(video_id, "PROVIDER_ERROR",
                            f"Provider returned HTTP {exc.status_code}",
                            http_status=502)

    except NoAudioFormatsError as exc:
        return stream_error(video_id, "NO_AUDIO_FORMATS", str(exc), http_status=422)

    except Exception as exc:
        log.error("[resolve/formats] Unexpected error videoId=%s: %s", video_id, exc)
        return stream_error(video_id, "INTERNAL_ERROR",
                            "Unexpected resolver error", http_status=500)
