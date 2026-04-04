"""
app/resolver/fallback_policy.py
Strategy constants and ordering concepts for multi-provider fallback.

Phase 3 (current):
  PRIMARY  = Cobalt (3 instances tried in order)
  FALLBACK = Invidious
  DISABLED = Piped (code present, excluded from runtime)

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
# Active runtime provider order (Phase 3)
#
# index 0 = primary, tried first.
# Piped remains disabled — its code is preserved for future reactivation.
# ---------------------------------------------------------------------------
ACTIVE_PROVIDER_ORDER = ["cobalt", "invidious"]  # Phase 3: Cobalt primary, Invidious fallback

# Providers present in codebase but excluded from runtime selection.
DISABLED_PROVIDERS = ["piped"]  # disabled: public instances unreliable

DEFAULT_POLICY = ProviderPolicy(
    provider_names=ACTIVE_PROVIDER_ORDER,
    strategy=ACTIVE_STRATEGY,
)

