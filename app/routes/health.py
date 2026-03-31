"""
app/routes/health.py — Health check endpoint.
"""
from fastapi import APIRouter
from app.config import PROVIDER_NAME
from app.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """
    Railway / uptime health check.
    Returns service name and current Invidious provider slug.
    """
    return HealthResponse(
        status="ok",
        service="paax-stream",
        provider=PROVIDER_NAME,
    )
