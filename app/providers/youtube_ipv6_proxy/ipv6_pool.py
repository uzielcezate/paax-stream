"""
app/providers/youtube_ipv6_proxy/ipv6_pool.py
IPv6 address pool for source-platform request rotation.

Generates *IPV6_POOL_SIZE* consecutive addresses starting from
*IPV6_SUBNET_BASE* and exposes helpers to pick one at random.

Example pool (base = 2604:A880:4:1D0::2:7D72:C000, size = 16):
  2604:a880:4:1d0::2:7d72:c000
  2604:a880:4:1d0::2:7d72:c001
  …
  2604:a880:4:1d0::2:7d72:c00f
"""
from __future__ import annotations

import ipaddress
import random
from typing import List

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)


def _build_pool(base_str: str, size: int) -> List[str]:
    """
    Generate *size* consecutive IPv6 addresses starting at *base_str*.
    Returns each as its **compressed** string representation.
    """
    base = ipaddress.IPv6Address(base_str)
    pool = [str(base + offset) for offset in range(size)]
    log.info(
        "[IPv6Pool] Built pool: %d addresses  (%s -> %s)",
        len(pool), pool[0], pool[-1],
    )
    return pool


# ── Module-level pool (created once at import) ───────────────────────────────
_POOL: List[str] = _build_pool(
    settings.IPV6_SUBNET_BASE,
    settings.IPV6_POOL_SIZE,
)


# ── Public API ────────────────────────────────────────────────────────────────

def get_random_address() -> str:
    """Return a random IPv6 from the pool."""
    addr = random.choice(_POOL)
    log.debug("[IPv6Pool] Selected %s", addr)
    return addr


def get_all_addresses() -> List[str]:
    """Return a copy of the full address pool (for health / debug)."""
    return list(_POOL)


def pool_size() -> int:
    """Number of addresses in the pool."""
    return len(_POOL)
