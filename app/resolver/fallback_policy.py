"""
app/resolver/fallback_policy.py
Strategy constants and ordering concepts for multi-provider fallback.

Phase 6 (current):
  PRIMARY  = youtube_ipv6_proxy (IPv6 rotation, Redis sessions, Range streaming)

Disabled (code retained for future use):
  - youtube_local_mp4 (first-party yt-dlp; direct CDN URL; no proxy)
  - cobalt            (public instances unreliable)
  - piped             (public instances unreliable)
  - invidious         (public instances unreliable)

DO NOT add new provider implementations here.
DO NOT change runtime behavior — this file is configuration only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class FallbackStrategy(str, Enum):
    """
    How provider_manager behaves when the primary provider fails.

    FIRST_SUCCESS  — try each provider in order; return on first success.
    PRIMARY_ONLY   — use only the first provider; never fall back.
    """
    FIRST_SUCCESS = "first_success"
    PRIMARY_ONLY  = "primary_only"


# Phase 6: FIRST_SUCCESS — ipv6_proxy only (single provider)
ACTIVE_STRATEGY: FallbackStrategy = FallbackStrategy.FIRST_SUCCESS


@dataclass
class ProviderPolicy:
    """
    Ordered provider list + fallback strategy.
    provider_names[0] is the primary provider.
    """
    provider_names:            List[str]        = field(default_factory=list)
    strategy:                  FallbackStrategy = FallbackStrategy.FIRST_SUCCESS
    timeout_per_provider_s:    float            = 15.0
    max_attempts:              int              = 1  # per provider


# ---------------------------------------------------------------------------
# Active runtime provider order (Phase 6)
#
# youtube_ipv6_proxy is the only active provider.
# All other providers remain in code but are disabled from runtime.
# ---------------------------------------------------------------------------
ACTIVE_PROVIDER_ORDER = ["youtube_ipv6_proxy"]  # IPv6 proxy; no public proxies

# Providers present in codebase but excluded from runtime selection.
DISABLED_PROVIDERS = [
    "youtube_local_mp4",  # Phase 5 — direct CDN URL (no proxy)
    "cobalt",             # public instances unreliable; code preserved
    "piped",              # public instances unreliable; code preserved
    "invidious",          # public instances unreliable; code preserved
]

DEFAULT_POLICY = ProviderPolicy(
    provider_names=ACTIVE_PROVIDER_ORDER,
    strategy=ACTIVE_STRATEGY,
)
