"""
app/utils/errors.py — Custom exceptions and error response helpers.
"""
from fastapi.responses import JSONResponse
from app.config import PROVIDER_NAME


class InvidiousTimeoutError(Exception):
    """Invidious request exceeded the configured timeout."""


class InvidiousUpstreamError(Exception):
    """Invidious returned a non-200 response."""
    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Invidious HTTP {status_code}")


class NoAudioFormatsError(Exception):
    """Video exists but contains no playable audio formats."""


class InvalidVideoIdError(Exception):
    """videoId is empty or obviously invalid."""


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
