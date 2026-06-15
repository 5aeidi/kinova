"""Movie routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import get_kinoheld_service
from app.schemas.movie import Movie, MovieSearchParams
from app.services.kinoheld import KinoheldService

router = APIRouter(prefix="/movies", tags=["movies"])

ServiceDep = Annotated[KinoheldService, Depends(get_kinoheld_service)]


@router.get("", response_model=list[Movie])
async def list_movies(
    params: Annotated[MovieSearchParams, Depends()],
    service: ServiceDep,
) -> list[Movie]:
    """Search movies by title or playing location."""
    return await service.search_movies(params)


@router.get("/{movie_id}", response_model=Movie)
async def get_movie(
    movie_id: Annotated[str, Path(..., description="Kinoheld movie ID")],
    service: ServiceDep,
) -> Movie:
    """Fetch a single movie by ID."""
    return await service.get_movie(movie_id)
