"""Response model for the health endpoint."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Payload returned by GET /api/health."""

    status: str
    version: str