"""
app/resolver/fallback_policy.py
Strategy constants and ordering concepts for multi-provider fallback.

Phase 2b (current):
  ACTIVE    = Invidious only
  DISABLED  = Piped (code present, excluded from runtime — public instances unreliable)
  PLANNED   = Cobalt (next primary once implemented)

Phase 3 (next): Cobalt primary + Invidious fallback.
Phase 4 (future): Deezer experimental.

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


# Phase 2: FIRST_SUCCESS — Piped → Invidious fallback
ACTIVE_STRATEGY: FallbackStrategy = FallbackStrategy.FIRST_SUCCESS


@dataclass
class ProviderPolicy:
    """
    Ordered provider list + fallback strategy.
    provider_names[0] is the primary provider.
    """
    provider_names:            List[str]        = field(default_factory=list)
    strategy:                  FallbackStrategy = FallbackStrategy.FIRST_SUCCESS
    timeout_per_provider_s:    float            = 10.0
    max_attempts:              int              = 1  # per provider


# ---------------------------------------------------------------------------
# Active runtime provider order (Phase 2b)
#
# Only providers listed here are used at runtime.
# Piped is intentionally excluded — its code is preserved for reactivation.
# Cobalt will be inserted before Invidious once implemented (Phase 3).
# ---------------------------------------------------------------------------
ACTIVE_PROVIDER_ORDER = ["invidious"]  # Phase 2b: Invidious only

# Providers present in codebase but excluded from runtime selection.
# Remove from this list to reactivate.
DISABLED_PROVIDERS = ["piped"]  # disabled: public instances unreliable

DEFAULT_POLICY = ProviderPolicy(
    provider_names=ACTIVE_PROVIDER_ORDER,
    strategy=ACTIVE_STRATEGY,
)

