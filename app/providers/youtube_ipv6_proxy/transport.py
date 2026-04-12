"""
app/providers/youtube_ipv6_proxy/transport.py
IPv6-bound httpx.AsyncClient factory.

Creates and caches ``httpx.AsyncClient`` instances that bind outgoing
connections to a specific local IPv6 address.  This is the mechanism
by which each request appears to come from a different IP to the
upstream CDN.

NOTE: Default headers do NOT include a ``User-Agent``.  The per-session
sticky UA (from ``SessionManager``) is injected per-request by the
streaming route so each IPv6 always identifies as the same device.

Usage::

    client = transport_pool.get_client("2604:a880:4:1d0::2:7d72:c003")
    resp = await client.get("https://...", headers={"User-Agent": session.user_agent})
"""
from __future__ import annotations

from typing import Dict

import httpx

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)


class TransportPool:
    """
    Maintains a pool of ``httpx.AsyncClient`` instances, one per IPv6.

    Clients are created lazily on first use and reused across requests
    to amortise TCP/TLS setup cost.

    Call ``shutdown()`` once at app teardown to close all connections.
    """

    def __init__(self) -> None:
        self._clients: Dict[str, httpx.AsyncClient] = {}

    def get_client(self, local_address: str) -> httpx.AsyncClient:
        """
        Return (or create) an ``AsyncClient`` bound to *local_address*.

        The client has NO default User-Agent — callers must supply one
        per-request from the session's sticky UA.
        """
        if local_address not in self._clients:
            transport = httpx.AsyncHTTPTransport(
                local_address=local_address,
                retries=1,
            )
            client = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=settings.UPSTREAM_TIMEOUT_S,
                    write=10.0,
                    pool=10.0,
                ),
                headers={
                    # User-Agent is intentionally OMITTED here.
                    # It is injected per-request from the session's sticky UA.
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": settings.SOURCE_PLATFORM_URL,
                    "Referer": f"{settings.SOURCE_PLATFORM_URL}/",
                },
                follow_redirects=True,
                http2=True,
            )
            self._clients[local_address] = client
            log.info("[TransportPool] Created client bound to %s (no default UA)", local_address)
        return self._clients[local_address]

    async def shutdown(self) -> None:
        """Close all cached httpx clients."""
        for addr, client in self._clients.items():
            try:
                await client.aclose()
                log.debug("[TransportPool] Closed client %s", addr)
            except Exception as exc:
                log.warning("[TransportPool] Error closing client %s: %s", addr, exc)
        self._clients.clear()
        log.info("[TransportPool] All clients closed.")


# ── Singleton ─────────────────────────────────────────────────────────────────
transport_pool = TransportPool()
