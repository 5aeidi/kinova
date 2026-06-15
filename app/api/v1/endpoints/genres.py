"""Genre routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_kinoheld_service
from app.schemas.movie import Genre
from app.services.kinoheld import KinoheldService

router = APIRouter(prefix="/genres", tags=["genres"])

ServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]


@router.get("", response_model=list[Genre])
async def list_genres(service: ServiceDep) -> list[Genre]:
    """List all available movie genres."""
    return await service.list_genres()
