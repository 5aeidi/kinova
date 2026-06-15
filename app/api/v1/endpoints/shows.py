"""Show / screening routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_kinoheld_service
from app.schemas.show import Show, ShowSearchParams
from app.services.kinoheld import KinoheldService

router = APIRouter(prefix="/shows", tags=["shows"])

ServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]


@router.get("", response_model=list[Show])
async def list_shows(
    params: Annotated[ShowSearchParams, Depends()],
    service: ServiceDep,
) -> list[Show]:
    """List shows for a cinema, optionally filtered by date and movie."""
    return await service.search_shows(params)


@router.get("/{show_id}", response_model=Show)
async def get_show(
    show_id: Annotated[str, Path(..., description="Kinoheld show ID")],
    service: ServiceDep,
) -> Show:
    """Fetch a single show by ID."""
    return await service.get_show(show_id)
