"""
app/routes/stream.py
Core streaming endpoint -- HTTP 206 Range Request proxy.

GET /stream/{video_id}

Flow:
  1. Parse the client's ``Range`` header.
  2. Look up the resolved CDN URL from the in-memory cache (populated by
     the provider's ``resolve_stream()``).  If missing, resolve on the fly.
  3. Pick a random IPv6 from the pool.
  4. Acquire session (cookies + sticky User-Agent) for that IPv6 from Redis.
  5. Open an httpx streaming request to the CDN, forwarding the Range header
     using the session's sticky UA so the IPv6 always looks like the same device.
  6. Yield chunks back to the client via ``StreamingResponse``.

Headers returned:
  - ``Accept-Ranges: bytes``
  - ``Content-Range: bytes START-END/TOTAL``
  - ``Content-Length``
  - ``Content-Type: audio/mp4``

This allows ``just_audio`` (ExoPlayer) to seek freely.
"""
from __future__ import annotations

import re
from typing import AsyncIterator, Optional, Tuple

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.providers.youtube_ipv6_proxy._cdn_cache import cdn_cache
from app.providers.youtube_ipv6_proxy.ipv6_pool import get_random_address
from app.providers.youtube_ipv6_proxy.resolver import resolve_m4a_url, ResolvedAudio
from app.providers.youtube_ipv6_proxy.session_manager import session_manager
from app.providers.youtube_ipv6_proxy.transport import transport_pool
from app.utils.errors import (
    InvalidVideoIdError,
    NoAudioFormatsError,
    InvidiousUpstreamError,
    UpstreamRateLimitError,
    UpstreamUnavailableError,
    RangeNotSatisfiableError,
)
from app.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter()

# ── Range header regex ────────────────────────────────────────────────────────
_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


def _parse_range(header: Optional[str]) -> Optional[Tuple[int, Optional[int]]]:
    """
    Parse an HTTP Range header like ``bytes=0-`` or ``bytes=1024-2048``.
    Returns ``(start, end_or_none)`` or ``None`` for no / invalid header.
    """
    if not header:
        return None
    m = _RANGE_RE.match(header.strip())
    if not m:
        return None
    start = int(m.group(1))
    end_s = m.group(2)
    end = int(end_s) if end_s else None
    return (start, end)


# ── Streaming generator ──────────────────────────────────────────────────────

async def _stream_chunks(
    response: httpx.Response,
    chunk_size: int,
) -> AsyncIterator[bytes]:
    """
    Yield bytes from an httpx streaming response without buffering
    the entire file in memory.
    """
    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
        yield chunk
    await response.aclose()


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get(
    "/stream/{video_id}",
    summary="Stream audio via IPv6 proxy (supports Range requests)",
    responses={
        200: {"description": "Full audio stream (no Range header)"},
        206: {"description": "Partial audio stream (Range header)"},
        400: {"description": "Invalid video ID"},
        416: {"description": "Range not satisfiable"},
        429: {"description": "Upstream rate-limited"},
        502: {"description": "Upstream unavailable"},
    },
)
async def stream_audio(video_id: str, request: Request):
    """
    Stream ``.m4a`` audio for *video_id*.

    Supports ``Range`` requests for seamless seeking in mobile players.
    Audio bytes are proxied iteratively -- never buffered to disk or RAM.
    """
    video_id = video_id.strip()
    log.info("[stream] -> videoId=%s", video_id)

    # ── 1. Resolve CDN URL ────────────────────────────────────────────────────
    resolved: Optional[ResolvedAudio] = cdn_cache.get(video_id)
    if resolved is None:
        log.info("[stream] CDN cache miss for %s -- resolving", video_id)
        try:
            resolved = await resolve_m4a_url(video_id)
            cdn_cache.set(video_id, resolved)
        except InvalidVideoIdError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": "INVALID_VIDEO_ID", "detail": str(exc)},
            )
        except NoAudioFormatsError as exc:
            return JSONResponse(
                status_code=422,
                content={"error": "NO_AUDIO_FORMATS", "detail": str(exc)},
            )
        except InvidiousUpstreamError as exc:
            return JSONResponse(
                status_code=502,
                content={"error": "RESOLVE_FAILED", "detail": str(exc)},
            )
        except Exception as exc:
            log.error("[stream] Unexpected resolve error: %s", exc)
            return JSONResponse(
                status_code=502,
                content={"error": "RESOLVE_FAILED", "detail": str(exc)},
            )

    cdn_url = resolved.stream_url
    log.info(
        "[stream] CDN URL ready for %s (itag=%s, bitrate=%d)",
        video_id, resolved.itag, resolved.bitrate,
    )

    # ── 2. Parse client Range ─────────────────────────────────────────────────
    range_header = request.headers.get("range")
    parsed_range = _parse_range(range_header)
    log.info("[stream] Client Range: %s -> parsed=%s", range_header, parsed_range)

    # ── 3. Pick IPv6 + acquire session (cookies + sticky UA) ──────────────────
    ipv6 = get_random_address()
    client = transport_pool.get_client(ipv6)
    session = await session_manager.acquire_session(ipv6, http_client=client)
    log.info(
        "[stream] Using IPv6=%s cookies=%d ua=%.50s...",
        ipv6, len(session.cookies), session.user_agent,
    )

    # ── 4. Build upstream request (using session's sticky UA) ─────────────────
    upstream_headers: dict[str, str] = {
        "User-Agent": session.user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": settings.SOURCE_PLATFORM_URL,
        "Referer": f"{settings.SOURCE_PLATFORM_URL}/",
    }

    if range_header:
        upstream_headers["Range"] = range_header

    # ── 5. Open upstream stream ───────────────────────────────────────────────
    try:
        upstream_resp = await client.send(
            client.build_request(
                "GET",
                cdn_url,
                headers=upstream_headers,
                cookies=session.cookies,
            ),
            stream=True,
        )
    except httpx.TimeoutException as exc:
        log.error("[stream] Upstream timeout for %s via %s: %s", video_id, ipv6, exc)
        return JSONResponse(
            status_code=504,
            content={"error": "UPSTREAM_TIMEOUT", "detail": str(exc)},
        )
    except httpx.HTTPError as exc:
        log.error("[stream] Upstream HTTP error for %s via %s: %s", video_id, ipv6, exc)
        return JSONResponse(
            status_code=502,
            content={"error": "UPSTREAM_ERROR", "detail": str(exc)},
        )

    # ── 6. Handle upstream status ─────────────────────────────────────────────
    us = upstream_resp.status_code

    if us == 429:
        await upstream_resp.aclose()
        retry_after = upstream_resp.headers.get("Retry-After")
        log.warning("[stream] 429 rate-limited on %s for %s", ipv6, video_id)
        return JSONResponse(
            status_code=429,
            content={"error": "RATE_LIMITED", "detail": f"IPv6 {ipv6} rate-limited"},
            headers={"Retry-After": retry_after or "30"},
        )

    if us in (502, 503):
        await upstream_resp.aclose()
        log.warning("[stream] Upstream %d for %s via %s", us, video_id, ipv6)
        return JSONResponse(
            status_code=502,
            content={"error": "UPSTREAM_UNAVAILABLE", "detail": f"CDN returned {us}"},
        )

    if us == 416:
        await upstream_resp.aclose()
        log.warning("[stream] 416 Range not satisfiable for %s", video_id)
        return JSONResponse(
            status_code=416,
            content={"error": "RANGE_NOT_SATISFIABLE", "detail": range_header},
        )

    if us == 403:
        await upstream_resp.aclose()
        # Invalidate cookies and CDN URL -- they're stale
        cdn_cache.delete(video_id)
        log.warning("[stream] 403 from CDN for %s via %s -- cache invalidated", video_id, ipv6)
        return JSONResponse(
            status_code=403,
            content={"error": "CDN_FORBIDDEN", "detail": "Stream URL expired or blocked. Retry."},
        )

    if us not in (200, 206):
        await upstream_resp.aclose()
        log.error("[stream] Unexpected upstream status %d for %s", us, video_id)
        return JSONResponse(
            status_code=502,
            content={"error": "UPSTREAM_ERROR", "detail": f"Unexpected HTTP {us}"},
        )

    # ── 7. Build response headers ─────────────────────────────────────────────
    resp_headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Content-Type": resolved.mime_type or "audio/mp4",
        "X-Proxy-IPv6": ipv6,
        "X-Provider": "youtube_ipv6_proxy",
    }

    # Forward Content-Range from upstream (present on 206)
    content_range = upstream_resp.headers.get("content-range")
    if content_range:
        resp_headers["Content-Range"] = content_range

    # Forward Content-Length from upstream
    content_length = upstream_resp.headers.get("content-length")
    if content_length:
        resp_headers["Content-Length"] = content_length

    status_code = upstream_resp.status_code  # 200 or 206

    log.info(
        "[stream] Streaming %s -> client (status=%d range=%s clen=%s ipv6=%s)",
        video_id, status_code, content_range, content_length, ipv6,
    )

    # ── 8. Stream! ────────────────────────────────────────────────────────────
    return StreamingResponse(
        content=_stream_chunks(upstream_resp, settings.STREAM_CHUNK_SIZE),
        status_code=status_code,
        headers=resp_headers,
        media_type=resolved.mime_type or "audio/mp4",
    )
