"""
app/resolver/fallback_policy.py
Strategy constants and ordering concepts for multi-provider fallback.

Phase 1: Invidious is the only active provider.
         This module defines the structure for future expansion.

Phase 2 (planned): automatic fallback chain —
  Invidious → Piped → Cobalt (experimental)

DO NOT add new provider implementations here.
DO NOT change runtime behavior — this file is configuration only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class FallbackStrategy(str, Enum):
    """
    How provider_manager should behave when the primary provider fails.

    FIRST_SUCCESS  — try each provider in order; return the first success.
    PRIMARY_ONLY   — use only the first (primary) provider; never fall back.
    """
    FIRST_SUCCESS = "first_success"
    PRIMARY_ONLY  = "primary_only"


# Active strategy for Phase 1.
# Change to FIRST_SUCCESS when additional providers are registered.
ACTIVE_STRATEGY: FallbackStrategy = FallbackStrategy.PRIMARY_ONLY


@dataclass
class ProviderPolicy:
    """
    Ordered list of provider names and the fallback strategy to apply.

    provider_names is the priority order: index 0 is primary.
    """
    provider_names: List[str]            = field(default_factory=list)
    strategy:       FallbackStrategy     = FallbackStrategy.PRIMARY_ONLY
    timeout_per_provider_s: float        = 10.0
    max_attempts: int                    = 1  # per provider in FIRST_SUCCESS mode


# Default policy — single active provider
DEFAULT_POLICY = ProviderPolicy(
    provider_names=["invidious"],
    strategy=ACTIVE_STRATEGY,
)
