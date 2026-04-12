"""
app/utils/errors.py — Custom exceptions and error response helpers.

Exception hierarchy:

  ProviderError (base)
    ├── InvidiousTimeoutError      — provider request timed out
    ├── InvidiousUpstreamError     — provider returned non-200
    ├── NoAudioFormatsError        — no playable audio formats found
    ├── InvalidVideoIdError        — videoId is empty / malformed
    ├── UpstreamRateLimitError     — source returned 429
    ├── UpstreamUnavailableError   — source returned 502 / 503
    ├── RangeNotSatisfiableError   — client sent an invalid Range header
    └── SessionAcquisitionError    — Redis / cookie acquisition failed
"""
from __future__ import annotations

from fastapi.responses import JSONResponse

from app.config import PROVIDER_NAME


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Root exception for all provider-level failures."""


# ---------------------------------------------------------------------------
# Legacy (Invidious-era, kept for backward compat)
# ---------------------------------------------------------------------------

class InvidiousTimeoutError(ProviderError):
    """Provider request exceeded the configured timeout."""


class InvidiousUpstreamError(ProviderError):
    """Provider returned a non-200 response."""

    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Provider HTTP {status_code}")


class NoAudioFormatsError(ProviderError):
    """Video exists but contains no playable audio formats."""


class InvalidVideoIdError(ProviderError):
    """videoId is empty or obviously invalid."""


# ---------------------------------------------------------------------------
# IPv6 Proxy era
# ---------------------------------------------------------------------------

class UpstreamRateLimitError(ProviderError):
    """Source platform returned HTTP 429 (too many requests)."""

    def __init__(self, ipv6_addr: str = "", retry_after: int | None = None) -> None:
        self.ipv6_addr = ipv6_addr
        self.retry_after = retry_after
        detail = f"Rate-limited on {ipv6_addr}" if ipv6_addr else "Rate-limited"
        if retry_after:
            detail += f" (retry-after {retry_after}s)"
        super().__init__(detail)


class UpstreamUnavailableError(ProviderError):
    """Source platform returned 502 / 503 — temporarily unavailable."""

    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Upstream HTTP {status_code}")


class RangeNotSatisfiableError(ProviderError):
    """Client sent a Range header the upstream cannot satisfy (HTTP 416)."""

    def __init__(self, requested_range: str = "", total_size: int | None = None) -> None:
        self.requested_range = requested_range
        self.total_size = total_size
        super().__init__(
            f"Range not satisfiable: {requested_range}"
            + (f" (total {total_size})" if total_size else "")
        )


class SessionAcquisitionError(ProviderError):
    """Failed to acquire / restore a session for an IPv6 address."""

    def __init__(self, ipv6_addr: str = "", reason: str = "") -> None:
        self.ipv6_addr = ipv6_addr
        msg = f"Session acquisition failed for {ipv6_addr}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stream_error(
    video_id: str,
    error: str,
    detail: str | None = None,
    http_status: int = 502,
) -> JSONResponse:
    """Return a clean JSON error response for stream resolution failures."""
    return JSONResponse(
        status_code=http_status,
        content={
            "success": False,
            "videoId": video_id,
            "provider": PROVIDER_NAME,
            "error": error,
            "detail": detail,
        },
    )
