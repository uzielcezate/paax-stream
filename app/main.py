"""
app/main.py -- paax-stream FastAPI entry point.

Service: paax-stream
Role: Pure IPv6 streaming proxy for the Paax music app.
Does NOT: extraction, metadata, search, catalog, or any frontend logic.

Phase 8 -- Hybrid Architecture:
  - Extraction: Flutter client (youtube_explode_dart on residential IP)
  - Streaming:  This server (IPv6 rotation, Redis sessions, Range support)
  - Endpoint:   /stream?url=<cdn_url>  -- chunked audio via HTTP 206
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
from app.providers.youtube_ipv6_proxy.session_manager import session_manager
from app.providers.youtube_ipv6_proxy.transport import transport_pool
from app.providers.youtube_ipv6_proxy.ua_pool import ua_pool_size
from app.routes.health import router as health_router
from app.routes.stream import router as stream_router
from app.utils.logging import get_logger

log = get_logger("paax-stream")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("paax-stream starting up (Phase 8 -- Hybrid Proxy)")
    log.info("  Mode       : Pure IPv6 streaming proxy")
    log.info("  Extraction : Client-side (youtube_explode_dart)")
    log.info("  IPv6 pool  : %d addresses", pool_size())
    addrs = get_all_addresses()
    log.info("  IPv6 range : %s -> %s", addrs[0], addrs[-1])
    log.info("  UA pool    : %d device profiles", ua_pool_size())
    log.info("  Redis      : %s", settings.REDIS_URL)
    log.info("  Chunk size : %d bytes", settings.STREAM_CHUNK_SIZE)
    log.info("  CORS       : %s", get_cors_origins())
    log.info("  Listening  : http://%s:%d", HOST, PORT)
    log.info("=" * 60)

    # Connect Redis for IPv6 sessions (cookies + sticky UA)
    await session_manager.startup()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("paax-stream shutting down.")
    await session_manager.shutdown()
    await transport_pool.shutdown()


app = FastAPI(
    title="paax-stream",
    description=(
        "Pure IPv6 streaming proxy for Paax. "
        "Accepts raw CDN audio URLs from the Flutter client and proxies them "
        "through a 16-address IPv6 rotation pool with per-IP device "
        "fingerprinting (User-Agent + cookies). Supports HTTP 206 Range "
        "requests for seamless seeking. "
        "Does NOT handle extraction, metadata, search, or catalog."
    ),
    version="4.0.0",
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
app.include_router(stream_router)


@app.get("/")
def root():
    return {
        "service":    "paax-stream",
        "version":    "4.0.0",
        "status":     "running",
        "mode":       "hybrid_proxy",
        "extraction": "client-side (youtube_explode_dart)",
        "streaming":  "server-side (ipv6 rotation + range proxy)",
        "docs":       "/docs",
        "health":     "/health",
        "endpoints": {
            "stream": "/stream?url={encoded_cdn_url}",
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
