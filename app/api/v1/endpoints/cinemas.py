"""Cinema routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_kinoheld_service
from app.schemas.cinema import Cinema, CinemaSearchParams
from app.services.kinoheld import KinoheldService

router = APIRouter(prefix="/cinemas", tags=["cinemas"])

ServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]


@router.get("", response_model=list[Cinema])
async def list_cinemas(
    params: Annotated[CinemaSearchParams, Depends()],
    service: ServiceDep,
) -> list[Cinema]:
    """Search cinemas by city, name, or free-text query."""
    return await service.search_cinemas(params)


@router.get("/{cinema_id}", response_model=Cinema)
async def get_cinema(
    cinema_id: Annotated[str, Path(..., description="Kinoheld cinema ID")],
    service: ServiceDep,
) -> Cinema:
    """Fetch a single cinema by ID."""
    return await service.get_cinema(cinema_id)
