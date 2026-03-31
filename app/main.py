"""
app/main.py — paax-stream FastAPI entry point.

Service: paax-stream
Role: Stream URL resolution via Invidious for the Paax music app.
Does NOT: metadata, search, catalog, library, or any frontend logic.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    PORT, HOST, PROVIDER_NAME, INVIDIOUS_BASE_URL,
    CACHE_TTL_SECONDS, get_cors_origins,
)
from app.routes.health import router as health_router
from app.routes.resolve import router as resolve_router
from app.utils.logging import get_logger

log = get_logger("paax-stream")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=" * 60)
    log.info("paax-stream starting up")
    log.info("  Provider  : %s (%s)", PROVIDER_NAME, INVIDIOUS_BASE_URL)
    log.info("  Cache TTL : %d seconds", CACHE_TTL_SECONDS)
    log.info("  CORS      : %s", get_cors_origins())
    log.info("  Listening : http://%s:%d", HOST, PORT)
    log.info("=" * 60)
    yield
    log.info("paax-stream shutting down.")


app = FastAPI(
    title="paax-stream",
    description=(
        "Stream URL resolution backend for Paax. "
        "Resolves YouTube audio streams via Invidious. "
        "Does NOT handle metadata, search, or catalog."
    ),
    version="1.0.0",
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
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(health_router)
app.include_router(resolve_router)


@app.get("/")
def root():
    return {
        "service":  "paax-stream",
        "status":   "running",
        "provider": PROVIDER_NAME,
        "docs":     "/docs",
        "health":   "/health",
    }


# ---------------------------------------------------------------------------
# Direct execution (local dev)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"[paax-stream] Starting on http://0.0.0.0:{port}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
