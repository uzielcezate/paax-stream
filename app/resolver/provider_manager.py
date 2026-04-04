"""
app/resolver/provider_manager.py
Central orchestration layer for stream resolution.

Phase 4 (pre-migration) — no active providers:
  All public-instance providers are disabled from runtime.
  youtube_local_mp4 will become the primary active provider in the next prompt.

Disabled (code retained for future use):
  - CobaltProvider    (public instances unreliable)
  - InvidiousProvider (public instances unreliable)
  - PipedProvider     (public instances unreliable)

Routes call provider_manager — they never import provider classes directly.
The manager owns the in-memory cache so providers remain stateless.
"""
from typing import Dict, List, Optional

from app.providers.base import StreamProvider, ResolvedStream, AudioFormat, ProviderStatus
# ---------------------------------------------------------------------------
# All public-instance providers are disabled from runtime (Phase 4).
# Un-comment and add to _providers below to re-enable any of them.
# ---------------------------------------------------------------------------
# from app.providers.cobalt.provider import CobaltProvider
# from app.providers.invidious.provider import InvidiousProvider
# from app.providers.piped.provider import PipedProvider
from app.resolver.fallback_policy import DEFAULT_POLICY, FallbackStrategy
from app.services.cache_service import stream_cache
from app.utils.logging import get_logger

log = get_logger(__name__)


class ProviderManager:
    """
    Orchestrates registered providers for stream resolution.

    Responsibilities:
      - Maintain an ordered list of providers (index 0 = primary)
      - Check / populate in-memory cache before hitting any provider
      - Apply the active FallbackStrategy when a provider fails
      - Return normalised result dicts to route handlers
    """

    def __init__(self) -> None:
        # ── Active providers (Phase 4 — pre-migration) ───────────────────────
        # No public providers are active. youtube_local_mp4 will be registered
        # here in the next prompt as the first-party primary provider.
        #
        # DISABLED (code retained, not loaded at runtime):
        #   CobaltProvider()    — re-enable when reliable
        #   InvidiousProvider() — re-enable when reliable
        #   PipedProvider()     — re-enable when reliable
        self._providers: List[StreamProvider] = []  # empty until youtube_local_mp4 is added
        self._policy = DEFAULT_POLICY
        log.info(
            "[ProviderManager] Initialised — providers=%s strategy=%s",
            [p.name for p in self._providers],
            self._policy.strategy.value,
        )
        if not self._providers:
            log.warning(
                "[ProviderManager] No active providers registered. "
                "All resolve calls will return PROVIDER_UNAVAILABLE until "
                "youtube_local_mp4 is added."
            )

    # ── Public interface used by routes ──────────────────────────────────────

    async def resolve_stream(self, video_id: str) -> Dict:
        """
        Resolve the best audio stream for video_id.

        1. Check in-memory cache (returns immediately on hit).
        2. Try providers in order per the active FallbackStrategy.
        3. Prime cache on success and return normalised response dict.

        Returns a dict ready for JSONResponse:
          { success, videoId, provider, streamUrl, mimeType, container, bitrate, cache }

        Raises the last provider exception on total failure (all providers exhausted).
        """
        # ── Cache check ───────────────────────────────────────────────────────
        cached = stream_cache.get(video_id)
        if cached is not None:
            log.info("[ProviderManager] Cache HIT videoId=%s", video_id)
            return {**cached, "cache": {"hit": True, "layer": "memory"}}

        # ── Provider resolution ───────────────────────────────────────────────
        result:   Optional[ResolvedStream] = None
        last_exc: Optional[Exception]      = None

        for provider in self._providers:
            try:
                log.info(
                    "[ProviderManager] Trying provider=%s videoId=%s",
                    provider.name, video_id,
                )
                result = await provider.resolve_stream(video_id)
                log.info(
                    "[ProviderManager] Success provider=%s videoId=%s "
                    "mimeType=%s bitrate=%d",
                    provider.name, video_id,
                    result.mime_type, result.bitrate,
                )
                break  # first success wins

            except Exception as exc:
                last_exc = exc
                log.warning(
                    "[ProviderManager] Provider %s failed for videoId=%s: %s — %s",
                    provider.name, video_id,
                    type(exc).__name__, exc,
                )
                if self._policy.strategy == FallbackStrategy.PRIMARY_ONLY:
                    break  # do not try next provider

                log.info(
                    "[ProviderManager] Falling back from %s → next provider",
                    provider.name,
                )
                # FIRST_SUCCESS: continue to the next registered provider

        if result is None:
            raise last_exc or RuntimeError("All providers failed")

        # ── Build payload + prime cache ───────────────────────────────────────
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
        Falls back to the next provider if the primary fails.

        Returns a dict ready for JSONResponse:
          { success, videoId, provider, formats }
        """
        last_exc: Optional[Exception] = None

        for provider in self._providers:
            try:
                formats: List[AudioFormat] = await provider.resolve_formats(video_id)
                log.info(
                    "[ProviderManager] resolve_formats provider=%s videoId=%s formats=%d",
                    provider.name, video_id, len(formats),
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
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "[ProviderManager] resolve_formats: provider %s failed for videoId=%s: %s",
                    provider.name, video_id, exc,
                )
                if self._policy.strategy == FallbackStrategy.PRIMARY_ONLY:
                    break

        raise last_exc or RuntimeError("All providers failed for resolve_formats")

    def provider_statuses(self) -> List[ProviderStatus]:
        """Return health metadata for every registered provider."""
        return [p.status() for p in self._providers]


# Singleton — imported once by route handlers and app.main
provider_manager = ProviderManager()
