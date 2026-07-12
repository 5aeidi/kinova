"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    cinemas,
    cinetixx,
    cities,
    genres,
    health,
    internal,
    movies,
    search,
    shows,
    unified,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(internal.router)
api_router.include_router(search.router)
api_router.include_router(cinemas.router)
api_router.include_router(movies.router)
api_router.include_router(shows.router)
api_router.include_router(cities.router)
api_router.include_router(genres.router)
api_router.include_router(cinetixx.router)
api_router.include_router(unified.router)
