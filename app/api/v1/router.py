"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import cinemas, cities, genres, health, internal, movies, shows

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(internal.router)
api_router.include_router(cinemas.router)
api_router.include_router(movies.router)
api_router.include_router(shows.router)
api_router.include_router(cities.router)
api_router.include_router(genres.router)
