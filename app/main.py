"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import KinovaError, generic_exception_handler, kinova_exception_handler

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def create_application() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.app_name,
        description="Kinova — a RESTful wrapper around the Kinoheld GraphQL API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    app.add_exception_handler(KinovaError, kinova_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    return app


app = create_application()
