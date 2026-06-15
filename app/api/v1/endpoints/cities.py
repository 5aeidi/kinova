"""City routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_kinoheld_service
from app.schemas.city import City, CitySearchParams
from app.services.kinoheld import KinoheldService

router = APIRouter(prefix="/cities", tags=["cities"])

ServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]


@router.get("", response_model=list[City])
async def list_cities(
    params: Annotated[CitySearchParams, Depends()],
    service: ServiceDep,
) -> list[City]:
    """Search cities."""
    return await service.search_cities(params)


@router.get("/me", response_model=City)
async def city_by_ip(service: ServiceDep) -> City:
    """Return the city inferred from the request IP."""
    return await service.city_by_ip()
