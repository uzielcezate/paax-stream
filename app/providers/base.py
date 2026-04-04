"""
app/providers/base.py
Abstract base class for all stream providers in paax-stream.

Every provider (Invidious, Piped, Cobalt, …) must subclass StreamProvider
and implement resolve_stream() and resolve_formats().

The provider_manager calls these methods; routes never import provider
implementations directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------

@dataclass
class ResolvedStream:
    """Canonical output of a successful single-stream resolution."""
    video_id:   str
    provider:   str
    stream_url: str
    mime_type:  str
    container:  str
    bitrate:    int          # bps
    height:     int = 0     # px; 0 = not applicable (audio-only providers)


@dataclass
class AudioFormat:
    """One normalised audio format entry (used by resolve_formats)."""
    mime_type:  str
    container:  str
    bitrate:    int
    url:        str


@dataclass
class ProviderStatus:
    """Optional health / diagnostic info reported by a provider."""
    name:      str
    available: bool
    base_url:  str
    notes:     str = ""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class StreamProvider(ABC):
    """
    Interface all stream providers must satisfy.

    Providers are stateless — they do not manage caching.
    The provider_manager is responsible for caching.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short slug identifying this provider, e.g. 'invidious'."""

    @abstractmethod
    async def resolve_stream(self, video_id: str) -> ResolvedStream:
        """
        Resolve the single best playable audio stream for video_id.

        Raises:
          ProviderError — any unrecoverable provider-level failure.
        Sub-types (timeout, upstream, no formats) are defined in errors.py.
        """

    @abstractmethod
    async def resolve_formats(self, video_id: str) -> List[AudioFormat]:
        """
        Return all detected audio formats for video_id, sorted by preference.
        Used by the /resolve/formats debug endpoint.
        """

    def status(self) -> ProviderStatus:
        """Optional override — return health metadata for this provider."""
        return ProviderStatus(name=self.name, available=True, base_url="")
