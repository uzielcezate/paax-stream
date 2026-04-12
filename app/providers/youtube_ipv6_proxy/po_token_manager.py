"""
app/providers/youtube_ipv6_proxy/po_token_manager.py
Automated PO Token generation and Redis caching.

Uses ``youtube-po-token-generator`` (Node.js CLI) to create YouTube
identity tokens (visitorData + poToken), then caches them in Redis
with a 30-minute TTL.  These tokens are consumed by pytubefix to
bypass the "Sign in to confirm you're not a bot" gate.

Redis key:  ``paax:po_token``
Value:      JSON ``{"visitorData": "...", "poToken": "..."}``
TTL:        PO_TOKEN_TTL seconds (default 1800 / 30 min).

If Redis is unreachable, tokens are cached in-memory only.

Prerequisites on the VPS:
  - Node.js >= 18
  - ``npm install -g youtube-po-token-generator``
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)

_REDIS_KEY = "paax:po_token"
_TOKEN_TTL = 1800  # 30 minutes
_GENERATE_TIMEOUT = 60  # seconds to wait for the CLI tool


@dataclass(frozen=True)
class POToken:
    """Immutable pair of YouTube identity tokens."""
    visitor_data: str
    po_token: str


class POTokenManager:
    """
    Generates, caches, and serves PO tokens for pytubefix.

    Lifecycle:
      1. ``startup()``  -- connect to Redis (called from FastAPI lifespan)
      2. ``get_tokens()`` -- called per-extraction; returns cached or fresh
      3. ``invalidate()`` -- force regeneration (e.g. on 403 from CDN)
      4. ``shutdown()`` -- close Redis (called from FastAPI lifespan)
    """

    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._redis_ok: bool = False
        # In-memory fallback cache
        self._mem_cache: Optional[POToken] = None
        self._mem_expires_at: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Open a Redis connection for PO token caching."""
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self._redis.ping()
            self._redis_ok = True
            log.info("[POTokenManager] Redis connected: %s", settings.REDIS_URL)
        except Exception as exc:
            self._redis_ok = False
            log.warning(
                "[POTokenManager] Redis unavailable (%s) -- tokens cached in-memory only.",
                exc,
            )

    async def shutdown(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            log.info("[POTokenManager] Redis connection closed.")

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_tokens(self) -> POToken:
        """
        Return valid PO tokens (from cache or freshly generated).

        Lookup order:
          1. In-memory cache (fastest, no I/O)
          2. Redis cache (survives restarts)
          3. Generate fresh via ``youtube-po-token-generator``
        """
        # 1. In-memory cache
        if self._mem_cache and time.time() < self._mem_expires_at:
            log.debug("[POTokenManager] In-memory cache HIT")
            return self._mem_cache

        # 2. Redis cache
        cached = await self._get_from_redis()
        if cached is not None:
            log.info("[POTokenManager] Redis cache HIT")
            self._mem_cache = cached
            self._mem_expires_at = time.time() + _TOKEN_TTL
            return cached

        # 3. Generate fresh tokens
        log.info("[POTokenManager] Cache MISS -- generating new PO tokens...")
        token = await self._generate()

        # Store in both caches
        await self._store_in_redis(token)
        self._mem_cache = token
        self._mem_expires_at = time.time() + _TOKEN_TTL

        return token

    async def invalidate(self) -> None:
        """
        Force token regeneration on the next ``get_tokens()`` call.
        Use this when the CDN returns 403 (tokens may be stale).
        """
        self._mem_cache = None
        self._mem_expires_at = 0.0
        if self._redis_ok and self._redis:
            try:
                await self._redis.delete(_REDIS_KEY)
            except Exception:
                pass
        log.info("[POTokenManager] Tokens invalidated -- will regenerate on next request.")

    # ── Token generation ──────────────────────────────────────────────────────

    async def _generate(self) -> POToken:
        """
        Run ``youtube-po-token-generator`` as a subprocess and parse its
        JSON output: ``{"visitorData": "...", "poToken": "..."}``.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "youtube-po-token-generator",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=_GENERATE_TIMEOUT,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "youtube-po-token-generator not found. "
                "Install it: npm install -g youtube-po-token-generator"
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"youtube-po-token-generator timed out after {_GENERATE_TIMEOUT}s. "
                "Check that Node.js is working on the VPS."
            )

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            log.error("[POTokenManager] Generator failed (exit %d): %s", proc.returncode, err)
            raise RuntimeError(
                f"youtube-po-token-generator exited with code {proc.returncode}: {err}"
            )

        raw = stdout.decode(errors="replace").strip()
        log.debug("[POTokenManager] Raw output: %s", raw[:200])

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.error("[POTokenManager] Failed to parse JSON: %s -- raw: %s", exc, raw[:300])
            raise RuntimeError(f"Failed to parse PO token output as JSON: {exc}")

        visitor_data = data.get("visitorData")
        po_token = data.get("poToken")

        if not visitor_data or not po_token:
            raise RuntimeError(
                f"PO token output missing required fields. "
                f"Got keys: {list(data.keys())}"
            )

        token = POToken(visitor_data=visitor_data, po_token=po_token)
        log.info(
            "[POTokenManager] Generated new tokens -- "
            "visitorData=%.30s... poToken=%.30s...",
            token.visitor_data, token.po_token,
        )
        return token

    # ── Redis helpers ─────────────────────────────────────────────────────────

    async def _get_from_redis(self) -> Optional[POToken]:
        if not self._redis_ok or self._redis is None:
            return None
        try:
            raw = await self._redis.get(_REDIS_KEY)
            if raw is None:
                return None
            data = json.loads(raw)
            return POToken(
                visitor_data=data["visitorData"],
                po_token=data["poToken"],
            )
        except Exception as exc:
            log.warning("[POTokenManager] Redis GET failed: %s", exc)
            return None

    async def _store_in_redis(self, token: POToken) -> None:
        if not self._redis_ok or self._redis is None:
            return
        try:
            await self._redis.set(
                _REDIS_KEY,
                json.dumps({
                    "visitorData": token.visitor_data,
                    "poToken": token.po_token,
                }),
                ex=_TOKEN_TTL,
            )
            log.info("[POTokenManager] Stored tokens in Redis (TTL %ds)", _TOKEN_TTL)
        except Exception as exc:
            log.warning("[POTokenManager] Redis SET failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
po_token_manager = POTokenManager()
