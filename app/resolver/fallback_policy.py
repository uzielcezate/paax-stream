"""
app/resolver/fallback_policy.py
Strategy constants and ordering concepts for multi-provider fallback.

Phase 4 — pre-migration (current):
  ACTIVE    = none (all public-instance providers disabled from runtime)
  DISABLED  = cobalt, piped, invidious (code present, preserved for future)
  PLANNED   = youtube_local_mp4 (first-party resolver — next prompt)

Phase 5 (next): youtube_local_mp4 as primary, public providers as optional fallback.

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
# Active runtime provider order (Phase 4 — pre-migration)
#
# ALL public-instance providers are currently disabled from runtime.
# The next active provider (youtube_local_mp4) will be added in Phase 5.
#
# To re-enable a provider: move it from DISABLED_PROVIDERS to ACTIVE_PROVIDER_ORDER
# and register its class instance in provider_manager._providers.
# ---------------------------------------------------------------------------
ACTIVE_PROVIDER_ORDER: list = []  # no active providers until youtube_local_mp4 is added

# Providers present in codebase but excluded from runtime selection.
DISABLED_PROVIDERS = [
    "cobalt",     # public instances unreliable; code preserved
    "piped",      # public instances unreliable; code preserved
    "invidious",  # public instances unreliable; code preserved
]

DEFAULT_POLICY = ProviderPolicy(
    provider_names=ACTIVE_PROVIDER_ORDER,
    strategy=ACTIVE_STRATEGY,
)

