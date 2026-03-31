"""
app/models.py — Pydantic response models for paax-stream.
"""
from typing import Optional, List
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

class CacheInfo(BaseModel):
    hit: bool
    layer: str  # 'memory' | 'provider'


class AudioFormat(BaseModel):
    mimeType: str
    container: str
    bitrate: int
    url: str


# ---------------------------------------------------------------------------
# /resolve/stream/{videoId}
# ---------------------------------------------------------------------------

class StreamResponse(BaseModel):
    success: bool
    videoId: str
    provider: str
    streamUrl: str
    mimeType: str
    container: str
    bitrate: int
    cache: CacheInfo


class StreamErrorResponse(BaseModel):
    success: bool = False
    videoId: str
    provider: str
    error: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# /resolve/formats/{videoId}
# ---------------------------------------------------------------------------

class FormatsResponse(BaseModel):
    success: bool
    videoId: str
    provider: str
    formats: List[AudioFormat]


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    service: str
    provider: str
