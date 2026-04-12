"""
app/providers/youtube_ipv6_proxy/session_manager.py
Per-IPv6 session / cookie + User-Agent management backed by Redis.

Each of the 16 IPv6 addresses gets its own browser-like session consisting
of **cookies** and a **sticky User-Agent** (randomly assigned at first
handshake, reused for every future request from that address).

Redis key format:  ``paax:session:<compressed_ipv6>``
Value:             JSON object ``{"cookies": {...}, "user_agent": "..."}``
TTL:               SESSION_COOKIE_TTL seconds (default 1800 / 30 min).

If Redis is unreachable the manager does NOT crash — it falls back to
a fresh (un-cached) handshake every time and logs a warning.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.providers.youtube_ipv6_proxy.ua_pool import get_random_user_agent
from app.utils.logging import get_logger

log = get_logger(__name__)

_KEY_PREFIX = "paax:session:"


# ---------------------------------------------------------------------------
# Session data container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionData:
    """
    Immutable snapshot of a session for a specific IPv6 address.

    Attributes:
        cookies:    dict of cookie name -> value to inject into requests.
        user_agent: the sticky User-Agent string assigned to this IPv6.
    """
    cookies:    Dict[str, str] = field(default_factory=dict)
    user_agent: str = ""


class SessionManager:
    """
    Async, Redis-backed session manager scoped per IPv6 address.

    Each IPv6 gets a randomly-assigned User-Agent on first handshake.
    That UA is stored in Redis alongside cookies so every future request
    from the same IPv6 presents the exact same device fingerprint.

    Lifecycle:
      1. ``startup()``  -- call once from the FastAPI lifespan to connect.
      2. ``acquire_session()`` -- called per-request.
      3. ``shutdown()`` -- call once to close Redis.
    """

    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._redis_ok: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Open the Redis connection pool.  Safe to call multiple times."""
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Lightweight ping to verify connectivity
            await self._redis.ping()
            self._redis_ok = True
            log.info("[SessionManager] Redis connected: %s", settings.REDIS_URL)
        except Exception as exc:
            self._redis_ok = False
            log.warning(
                "[SessionManager] Redis unavailable (%s) -- sessions will NOT be cached. "
                "Every request will perform a fresh handshake.",
                exc,
            )

    async def shutdown(self) -> None:
        """Close Redis connection pool."""
        if self._redis is not None:
            await self._redis.aclose()
            log.info("[SessionManager] Redis connection closed.")

    # ── Public API ────────────────────────────────────────────────────────────

    async def acquire_session(
        self,
        ipv6_addr: str,
        *,
        http_client: httpx.AsyncClient,
    ) -> SessionData:
        """
        Return session data (cookies + sticky User-Agent) for *ipv6_addr*.

        1. Try Redis cache -- returns ``SessionData`` with persisted UA.
        2. On miss -- pick a random UA, perform handshake, store both in
           Redis, and return.
        """
        cached = await self._get_from_redis(ipv6_addr)
        if cached is not None:
            log.info(
                "[SessionManager] Cache HIT for %s (%d cookies, ua=%.40s...)",
                ipv6_addr, len(cached.cookies), cached.user_agent,
            )
            return cached

        # ── First contact: assign a device identity ───────────────────────────
        user_agent = get_random_user_agent()
        log.info(
            "[SessionManager] Cache MISS for %s -- assigning UA=%.60s...",
            ipv6_addr, user_agent,
        )

        cookies = await self._handshake(
            ipv6_addr,
            user_agent=user_agent,
            http_client=http_client,
        )

        session = SessionData(cookies=cookies, user_agent=user_agent)
        await self._store_in_redis(ipv6_addr, session)
        return session

    # ── Redis helpers ─────────────────────────────────────────────────────────

    async def _get_from_redis(self, ipv6_addr: str) -> Optional[SessionData]:
        if not self._redis_ok or self._redis is None:
            return None
        key = f"{_KEY_PREFIX}{ipv6_addr}"
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            # ── Handle legacy format (plain cookies dict) gracefully ──────────
            if isinstance(data, dict) and "user_agent" in data:
                return SessionData(
                    cookies=data.get("cookies", {}),
                    user_agent=data["user_agent"],
                )
            # Legacy: raw cookies dict without UA -- treat as miss so a new
            # UA is assigned and the entry is overwritten.
            log.info("[SessionManager] Legacy session format for %s -- re-creating", ipv6_addr)
            return None
        except Exception as exc:
            log.warning("[SessionManager] Redis GET failed for %s: %s", ipv6_addr, exc)
            return None

    async def _store_in_redis(self, ipv6_addr: str, session: SessionData) -> None:
        if not self._redis_ok or self._redis is None:
            return
        key = f"{_KEY_PREFIX}{ipv6_addr}"
        payload = {
            "cookies":    session.cookies,
            "user_agent": session.user_agent,
        }
        try:
            await self._redis.set(
                key,
                json.dumps(payload),
                ex=settings.SESSION_COOKIE_TTL,
            )
            log.info(
                "[SessionManager] Stored session for %s (%d cookies, TTL %ds, ua=%.40s...)",
                ipv6_addr, len(session.cookies),
                settings.SESSION_COOKIE_TTL, session.user_agent,
            )
        except Exception as exc:
            log.warning("[SessionManager] Redis SET failed for %s: %s", ipv6_addr, exc)

    # ── Handshake ─────────────────────────────────────────────────────────────

    async def _handshake(
        self,
        ipv6_addr: str,
        *,
        user_agent: str,
        http_client: httpx.AsyncClient,
    ) -> Dict[str, str]:
        """
        Make a GET / to the source platform root from the given IPv6,
        using the assigned User-Agent.  Extract and return Set-Cookie values.
        """
        source_url = settings.SOURCE_PLATFORM_URL.rstrip("/")
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            resp = await http_client.get(
                source_url,
                headers=headers,
                follow_redirects=True,
                timeout=10.0,
            )
            cookies: Dict[str, str] = dict(resp.cookies)
            log.info(
                "[SessionManager] Handshake OK for %s -- status=%d cookies=%d",
                ipv6_addr, resp.status_code, len(cookies),
            )
            return cookies
        except Exception as exc:
            log.warning(
                "[SessionManager] Handshake FAILED for %s: %s -- returning empty cookies",
                ipv6_addr, exc,
            )
            return {}


# ── Singleton ─────────────────────────────────────────────────────────────────
session_manager = SessionManager()
