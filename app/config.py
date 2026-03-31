"""
app/config.py — Environment-based configuration for paax-stream.
All values can be overridden via environment variables or a .env file.
"""
import os

# ---------------------------------------------------------------------------
# Invidious provider
# ---------------------------------------------------------------------------

INVIDIOUS_BASE_URL: str = os.getenv(
    "INVIDIOUS_BASE_URL", "https://invidious.nerdvpn.de"
).rstrip("/")

PROVIDER_NAME: str = "invidious-nerdvpn"

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT_S: float = float(os.getenv("REQUEST_TIMEOUT_MS", "8000")) / 1000

# ---------------------------------------------------------------------------
# Cache (in-memory)
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "600"))

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

PORT: int  = int(os.getenv("PORT", 8080))
HOST: str  = "0.0.0.0"

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

FRONTEND_ORIGINS_RAW: str = os.getenv("FRONTEND_ORIGINS", "*")

def get_cors_origins() -> list[str]:
    """Parse FRONTEND_ORIGINS into a list. '*' means allow all."""
    if FRONTEND_ORIGINS_RAW.strip() == "*":
        return ["*"]
    return [o.strip() for o in FRONTEND_ORIGINS_RAW.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "info").upper()
