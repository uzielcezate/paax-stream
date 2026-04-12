"""
app/main.py -- paax-stream FastAPI entry point.

Service: paax-stream
Role: Stream URL resolution + IPv6 proxy streaming for the Paax music app.
Does NOT: metadata, search, catalog, library, or any frontend logic.

Phase 7:
  - Extraction: pytubefix + PO tokens (self-contained, no external APIs)
  - Streaming:  IPv6 rotation, Redis sessions, Range streaming
  - Endpoint:   /stream/{videoId}  -- chunked .m4a audio via HTTP 206
  - Endpoint:   /resolve/stream/{videoId}  -- JSON metadata (proxy URL)
  - Endpoint:   /resolve/formats/{videoId} -- all audio formats (debug)
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    settings,
    PORT, HOST, PROVIDER_NAME,
    CACHE_TTL_SECONDS, get_cors_origins,
)
from app.providers.youtube_ipv6_proxy.ipv6_pool import pool_size, get_all_addresses
from app.providers.youtube_ipv6_proxy.po_token_manager import po_token_manager
from app.providers.youtube_ipv6_proxy.session_manager import session_manager
from app.providers.youtube_ipv6_proxy.transport import transport_pool
from app.providers.youtube_ipv6_proxy.ua_pool import ua_pool_size
from app.routes.health import router as health_router
from app.routes.resolve import router as resolve_router
from app.routes.stream import router as stream_router
from app.utils.logging import get_logger

log = get_logger("paax-stream")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("paax-stream starting up (Phase 7 -- pytubefix + PO Tokens)")
    log.info("  Provider   : %s", PROVIDER_NAME)
    log.info("  Extraction : pytubefix (self-contained, no Invidious)")
    log.info("  Source URL  : %s", settings.SOURCE_PLATFORM_URL)
    log.info("  IPv6 pool  : %d addresses", pool_size())
    addrs = get_all_addresses()
    log.info("  IPv6 range : %s -> %s", addrs[0], addrs[-1])
    log.info("  UA pool    : %d device profiles", ua_pool_size())
    log.info("  Redis      : %s", settings.REDIS_URL)
    log.info("  Cache TTL  : %d seconds", CACHE_TTL_SECONDS)
    log.info("  Chunk size : %d bytes", settings.STREAM_CHUNK_SIZE)
    log.info("  CORS       : %s", get_cors_origins())
    log.info("  Listening  : http://%s:%d", HOST, PORT)
    log.info("=" * 60)

    # Connect Redis for sessions + PO tokens
    await session_manager.startup()
    await po_token_manager.startup()

    # Pre-warm PO tokens so the first request isn't slow
    try:
        token = await po_token_manager.get_tokens()
        log.info(
            "  PO tokens  : READY (visitorData=%.30s...)",
            token.visitor_data,
        )
    except Exception as exc:
        log.warning(
            "  PO tokens  : FAILED to pre-warm (%s) -- will retry on first request",
            exc,
        )

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("paax-stream shutting down.")
    await po_token_manager.shutdown()
    await session_manager.shutdown()
    await transport_pool.shutdown()


app = FastAPI(
    title="paax-stream",
    description=(
        "Stream URL resolution + IPv6 proxy streaming backend for Paax. "
        "Resolves YouTube audio (M4A itag 140) via pytubefix with automated "
        "PO token generation. Streams via transparent proxy with IPv6 rotation, "
        "dynamic User-Agent pool, and Redis session management. "
        "Fully self-contained -- no external APIs (Invidious, Piped, etc.). "
        "Does NOT handle metadata, search, or catalog."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
origins = get_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=None if origins != ["*"] else None,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(health_router)
app.include_router(resolve_router)
app.include_router(stream_router)


@app.get("/")
def root():
    return {
        "service":    "paax-stream",
        "version":    "3.0.0",
        "status":     "running",
        "provider":   PROVIDER_NAME,
        "extraction": "pytubefix + po_token",
        "docs":       "/docs",
        "health":     "/health",
        "endpoints": {
            "stream":   "/stream/{videoId}",
            "resolve":  "/resolve/stream/{videoId}",
            "formats":  "/resolve/formats/{videoId}",
        },
    }


# ---------------------------------------------------------------------------
# Direct execution (local dev)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"[paax-stream] Starting on http://0.0.0.0:{port}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
