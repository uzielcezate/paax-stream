"""
app/config.py — Typed, validated configuration via pydantic-settings.

All values are read from environment variables or a .env file.
Import ``settings`` anywhere you need a config value:

    from app.config import settings
    print(settings.REDIS_URL)

Legacy module-level constants (PORT, HOST, …) are re-exported for backward
compatibility with existing imports.
"""
from __future__ import annotations

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object.
    Env vars are matched case-insensitively; .env file is loaded automatically.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",               # ignore unknown env vars
    )

    # ── Source platform (domain-agnostic) ─────────────────────────────────────
    SOURCE_PLATFORM_URL: str = "https://www.youtube.com"

    # ── IPv6 rotation ─────────────────────────────────────────────────────────
    IPV6_SUBNET_BASE: str = "2604:A880:0004:01D0:0000:0002:7D72:C000"
    IPV6_POOL_SIZE: int = 16

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    SESSION_COOKIE_TTL: int = 1800          # seconds

    # ── Streaming ─────────────────────────────────────────────────────────────
    STREAM_CHUNK_SIZE: int = 65_536         # 64 KiB
    UPSTREAM_TIMEOUT_S: float = 15.0

    # ── Invidious API (extraction backend) ───────────────────────────────────
    INVIDIOUS_BASE_URL: str = "https://invidious.nerdvpn.de"

    # ── HTTP client ───────────────────────────────────────────────────────────
    REQUEST_TIMEOUT_MS: int = 8000

    # ── In-memory cache ───────────────────────────────────────────────────────
    CACHE_TTL_SECONDS: int = 600

    # ── CORS ──────────────────────────────────────────────────────────────────
    FRONTEND_ORIGINS: str = "*"

    # ── Server ────────────────────────────────────────────────────────────────
    PORT: int = 8080
    HOST: str = "0.0.0.0"

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "info"

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def request_timeout_s(self) -> float:
        """REQUEST_TIMEOUT_MS converted to seconds."""
        return self.REQUEST_TIMEOUT_MS / 1000

    def get_cors_origins(self) -> List[str]:
        """Parse FRONTEND_ORIGINS into a list.  '*' means allow all."""
        raw = self.FRONTEND_ORIGINS.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


# ── Singleton ─────────────────────────────────────────────────────────────────
settings = Settings()

# ── Backward-compatible module-level re-exports ──────────────────────────────
# Existing code does:  from app.config import PORT, HOST, ...
# These aliases keep that working without mass-refactoring every import site.

PORT: int = settings.PORT
HOST: str = settings.HOST
PROVIDER_NAME: str = "youtube_ipv6_proxy"
INVIDIOUS_BASE_URL: str = settings.INVIDIOUS_BASE_URL.rstrip("/")
REQUEST_TIMEOUT_S: float = settings.request_timeout_s
CACHE_TTL_SECONDS: int = settings.CACHE_TTL_SECONDS
FRONTEND_ORIGINS_RAW: str = settings.FRONTEND_ORIGINS
LOG_LEVEL: str = settings.LOG_LEVEL.upper()


def get_cors_origins() -> list[str]:
    """Backward-compatible wrapper."""
    return settings.get_cors_origins()
