"""
app/routes/stream.py
Pure IPv6 streaming proxy -- HTTP 206 Range Request support.

GET /stream?url=<encoded_googlevideo_url>

Hybrid Architecture:
  The Flutter client extracts the raw CDN URL using youtube_explode_dart
  (on a residential IP, bypassing datacenter blocks).  It then passes that
  URL to this endpoint.  The server's ONLY job is to proxy the bytes
  through our IPv6 rotation pool with realistic device fingerprints.

Flow:
  1. Receive the raw CDN URL from the client (query param).
  2. Validate it's a legitimate googlevideo.com URL (anti-abuse).
  3. Parse the client's ``Range`` header.
  4. Pick a random IPv6 from the pool.
  5. Acquire session (cookies + sticky User-Agent) for that IPv6.
  6. Open an httpx streaming request to the CDN, forwarding the Range.
  7. Yield 64KB chunks back via ``StreamingResponse``.

Headers returned:
  - ``Accept-Ranges: bytes``
  - ``Content-Range: bytes START-END/TOTAL``
  - ``Content-Length``
  - ``Content-Type: audio/mp4``
"""
from __future__ import annotations

import re
from typing import AsyncIterator, Optional, Tuple
from urllib.parse import urlparse, unquote

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.providers.youtube_ipv6_proxy.ipv6_pool import get_random_address
from app.providers.youtube_ipv6_proxy.session_manager import session_manager
from app.providers.youtube_ipv6_proxy.transport import transport_pool
from app.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter()

# ── Allowed CDN hostnames (anti-abuse: prevents open proxy) ───────────────────
_ALLOWED_HOSTS = (
    ".googlevideo.com",
    ".youtube.com",
    ".ytimg.com",
    ".ggpht.com",
)

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


def _is_allowed_url(url: str) -> bool:
    """Validate that the URL points to a legitimate Google CDN host."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return any(host.endswith(allowed) for allowed in _ALLOWED_HOSTS)
    except Exception:
        return False


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
    "/stream",
    summary="IPv6 streaming proxy (accepts raw CDN URL from client)",
    responses={
        200: {"description": "Full audio stream (no Range header)"},
        206: {"description": "Partial audio stream (Range header)"},
        400: {"description": "Missing or invalid URL"},
        403: {"description": "CDN rejected the request"},
        416: {"description": "Range not satisfiable"},
        429: {"description": "Upstream rate-limited"},
        502: {"description": "Upstream unavailable"},
    },
)
async def stream_audio(
    request: Request,
    url: str = Query(
        ...,
        description="URL-encoded googlevideo.com CDN audio URL (provided by the client)",
    ),
):
    """
    Proxy audio bytes from a raw CDN URL through the IPv6 rotation pool.

    The Flutter client extracts the CDN URL via youtube_explode_dart and
    passes it here.  The server adds IPv6 rotation + device fingerprinting.

    Supports ``Range`` requests for seamless seeking in mobile players.
    Audio bytes are proxied iteratively -- never buffered to disk or RAM.
    """
    # ── 1. Validate the CDN URL ───────────────────────────────────────────────
    cdn_url = unquote(url).strip()

    if not cdn_url:
        return JSONResponse(
            status_code=400,
            content={"error": "MISSING_URL", "detail": "The 'url' query parameter is required."},
        )

    if not _is_allowed_url(cdn_url):
        log.warning("[stream] Rejected non-Google URL: %.100s...", cdn_url)
        return JSONResponse(
            status_code=400,
            content={
                "error": "INVALID_URL",
                "detail": "URL must point to a Google CDN host (*.googlevideo.com).",
            },
        )

    log.info("[stream] -> url=%.80s...", cdn_url)

    # ── 2. Parse client Range ─────────────────────────────────────────────────
    range_header = request.headers.get("range")
    parsed_range = _parse_range(range_header)
    log.debug("[stream] Client Range: %s -> parsed=%s", range_header, parsed_range)

    # ── 3. Pick IPv6 + acquire session (cookies + sticky UA) ──────────────────
    ipv6 = get_random_address()
    client = transport_pool.get_client(ipv6)
    session = await session_manager.acquire_session(ipv6, http_client=client)
    log.info(
        "[stream] IPv6=%s ua=%.50s...",
        ipv6, session.user_agent,
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
        log.error("[stream] Upstream timeout via %s: %s", ipv6, exc)
        return JSONResponse(
            status_code=504,
            content={"error": "UPSTREAM_TIMEOUT", "detail": str(exc)},
        )
    except httpx.HTTPError as exc:
        log.error("[stream] Upstream HTTP error via %s: %s", ipv6, exc)
        return JSONResponse(
            status_code=502,
            content={"error": "UPSTREAM_ERROR", "detail": str(exc)},
        )

    # ── 6. Handle upstream status ─────────────────────────────────────────────
    us = upstream_resp.status_code

    if us == 429:
        await upstream_resp.aclose()
        retry_after = upstream_resp.headers.get("Retry-After")
        log.warning("[stream] 429 rate-limited on %s", ipv6)
        return JSONResponse(
            status_code=429,
            content={"error": "RATE_LIMITED", "detail": f"IPv6 {ipv6} rate-limited"},
            headers={"Retry-After": retry_after or "30"},
        )

    if us in (502, 503):
        await upstream_resp.aclose()
        log.warning("[stream] Upstream %d via %s", us, ipv6)
        return JSONResponse(
            status_code=502,
            content={"error": "UPSTREAM_UNAVAILABLE", "detail": f"CDN returned {us}"},
        )

    if us == 416:
        await upstream_resp.aclose()
        log.warning("[stream] 416 Range not satisfiable")
        return JSONResponse(
            status_code=416,
            content={"error": "RANGE_NOT_SATISFIABLE", "detail": range_header},
        )

    if us == 403:
        await upstream_resp.aclose()
        log.warning("[stream] 403 from CDN via %s", ipv6)
        return JSONResponse(
            status_code=403,
            content={"error": "CDN_FORBIDDEN", "detail": "CDN rejected the request. URL may be expired."},
        )

    if us not in (200, 206):
        await upstream_resp.aclose()
        log.error("[stream] Unexpected upstream status %d", us)
        return JSONResponse(
            status_code=502,
            content={"error": "UPSTREAM_ERROR", "detail": f"Unexpected HTTP {us}"},
        )

    # ── 7. Build response headers ─────────────────────────────────────────────
    # Detect content type from upstream or default to audio/mp4
    upstream_ct = upstream_resp.headers.get("content-type", "audio/mp4")
    media_type = upstream_ct.split(";")[0].strip()

    resp_headers: dict[str, str] = {
        "Accept-Ranges": "bytes",
        "Content-Type": media_type,
        "X-Proxy-IPv6": ipv6,
        "X-Provider": "ipv6_proxy",
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
        "[stream] Proxying -> client (status=%d range=%s clen=%s ipv6=%s)",
        status_code, content_range, content_length, ipv6,
    )

    # ── 8. Stream! ────────────────────────────────────────────────────────────
    return StreamingResponse(
        content=_stream_chunks(upstream_resp, settings.STREAM_CHUNK_SIZE),
        status_code=status_code,
        headers=resp_headers,
        media_type=media_type,
    )
