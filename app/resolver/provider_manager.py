"""
app/resolver/provider_manager.py
Central orchestration layer for stream resolution.

Routes call provider_manager — they never import provider classes directly.

Phase 1: Orchestrates a single provider (Invidious).
Phase 2: Will iterate providers per FallbackStrategy when multiple are registered.

The manager also owns the in-memory cache so providers remain stateless.
"""
from typing import Dict, List, Optional

from app.providers.base import StreamProvider, ResolvedStream, AudioFormat, ProviderStatus
from app.providers.invidious.provider import InvidiousProvider
from app.resolver.fallback_policy import DEFAULT_POLICY, FallbackStrategy
from app.services.cache_service import stream_cache
from app.utils.logging import get_logger
from app.utils.errors import NoAudioFormatsError

log = get_logger(__name__)


class ProviderManager:
    """
    Orchestrates registered providers for stream resolution.

    Responsibilities:
      - Maintain an ordered list of providers
      - Check / populate in-memory cache
      - Apply fallback policy when resolution fails
      - Return normalised results to route handlers
    """

    def __init__(self) -> None:
        # Ordered by priority (index 0 = primary)
        self._providers: List[StreamProvider] = [
            InvidiousProvider(),
        ]
        self._policy = DEFAULT_POLICY
        log.info(
            "[ProviderManager] Initialised — providers=%s strategy=%s",
            [p.name for p in self._providers],
            self._policy.strategy.value,
        )

    # ── Public interface used by routes ──────────────────────────────────────

    async def resolve_stream(self, video_id: str) -> Dict:
        """
        Resolve the best audio stream for video_id.

        Returns a dict ready to be serialised as a JSON response:
          { success, videoId, provider, streamUrl, mimeType, container, bitrate, cache }

        Raises exceptions only for programmer errors; all provider failures
        are caught and returned as error dicts for the route to handle.
        """
        # ── 1. Cache check ────────────────────────────────────────────────────
        cached = stream_cache.get(video_id)
        if cached is not None:
            log.info("[ProviderManager] Cache HIT videoId=%s", video_id)
            return {**cached, "cache": {"hit": True, "layer": "memory"}}

        # ── 2. Provider resolution ────────────────────────────────────────────
        result: Optional[ResolvedStream] = None
        last_exc: Optional[Exception]   = None

        for provider in self._providers:
            try:
                result = await provider.resolve_stream(video_id)
                log.info(
                    "[ProviderManager] Resolved videoId=%s via provider=%s "
                    "mimeType=%s bitrate=%d",
                    video_id, provider.name, result.mime_type, result.bitrate,
                )
                break
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "[ProviderManager] Provider %s failed for videoId=%s: %s",
                    provider.name, video_id, exc,
                )
                if self._policy.strategy == FallbackStrategy.PRIMARY_ONLY:
                    break  # Phase 1: do not try further providers

        if result is None:
            # Re-raise the last exception so the route can map it to HTTP codes
            raise last_exc or RuntimeError("All providers failed")

        # ── 3. Build payload + prime cache ────────────────────────────────────
        payload = {
            "success":   True,
            "videoId":   result.video_id,
            "provider":  result.provider,
            "streamUrl": result.stream_url,
            "mimeType":  result.mime_type,
            "container": result.container,
            "bitrate":   result.bitrate,
        }
        stream_cache.set(video_id, payload)

        return {**payload, "cache": {"hit": False, "layer": "provider"}}

    async def resolve_formats(self, video_id: str) -> Dict:
        """
        Return all audio formats for video_id from the primary provider.

        Returns a dict ready for JSON serialisation:
          { success, videoId, provider, formats }
        """
        provider = self._providers[0]

        formats: List[AudioFormat] = await provider.resolve_formats(video_id)

        log.info(
            "[ProviderManager] resolve_formats videoId=%s provider=%s formats=%d",
            video_id, provider.name, len(formats),
        )

        return {
            "success":  True,
            "videoId":  video_id,
            "provider": provider.name,
            "formats": [
                {
                    "mimeType":  f.mime_type,
                    "container": f.container,
                    "bitrate":   f.bitrate,
                    "url":       f.url,
                }
                for f in formats
            ],
        }

    def provider_statuses(self) -> List[ProviderStatus]:
        """Return health metadata for every registered provider."""
        return [p.status() for p in self._providers]


# Singleton — imported once by route handlers
provider_manager = ProviderManager()
