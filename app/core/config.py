"""Application configuration loaded from environment variables."""

import json
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

StringList = Annotated[list[str], NoDecode]
IntList = Annotated[list[int], NoDecode]


def _parse_list_value(value: Any) -> list[Any]:
    """Parse JSON arrays, comma-separated strings, blank values, or existing lists."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON array")
            return parsed
        return [part.strip() for part in text.split(",") if part.strip()]
    return [value]


class Settings(BaseSettings):
    """Centralised application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Kinova", description="Application display name")
    debug: bool = Field(default=False, description="Enable debug mode")
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, description="Server bind port")

    # Kinoheld GraphQL API
    kinoheld_graphql_url: str = Field(
        default="https://graph.kinoheld.de/graphql/v1/query",
        description="Kinoheld GraphQL endpoint",
    )
    kinoheld_request_timeout: float = Field(
        default=30.0,
        description="HTTP request timeout in seconds",
    )
    kinoheld_pool_limits: int = Field(
        default=10,
        description="Max keepalive connections in the HTTP connection pool",
    )
    kinoheld_affiliate_key: str | None = Field(
        default=None,
        description="Optional affiliate key for commissionable links",
    )

    # Cinetixx legacy showtime endpoint
    cinetixx_show_info_url: str = Field(
        default="https://api.cinetixx.de/Services/CinetixxService.asmx/GetShowInfoV6",
        description="Cinetixx legacy showtime endpoint",
    )
    cinetixx_cinema_search_url: str = Field(
        default="https://booking.cinetixx.de/api/cinemas/",
        description="Cinetixx cinema discovery endpoint",
    )
    cinetixx_request_timeout: float = Field(
        default=30.0,
        description="Cinetixx HTTP request timeout in seconds",
    )
    cinetixx_pool_limits: int = Field(
        default=10,
        description="Max keepalive connections in the Cinetixx HTTP connection pool",
    )
    cinetixx_sync_interval_seconds: int = Field(
        default=600,
        description="How often to refresh the local Cinetixx cache",
    )
    cinetixx_sync_mandator_ids: IntList = Field(
        default_factory=list,
        description="Cinetixx mandator IDs to pre-fetch during cache refresh",
    )
    cinetixx_sync_discovery_searches: StringList = Field(
        default_factory=list,
        description="Cinetixx cinema search terms whose mandators are rediscovered on refresh",
    )
    cinetixx_sync_show_days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Default number of Cinetixx show days to return when filtering dates",
    )

    # Local cache / sync settings
    kinoheld_sync_interval_seconds: int = Field(
        default=600,
        description="How often to refresh the local Kinoheld cache",
    )
    kinoheld_sync_cinema_ids: StringList = Field(
        default_factory=list,
        description="Cinema IDs to pre-fetch shows for during cache refresh",
    )
    kinoheld_sync_show_days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Number of days to fetch shows for during cache refresh",
    )
    kinoheld_sync_movie_limit: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Max movies to fetch per cache refresh",
    )
    kinoheld_sync_cinema_limit: int = Field(
        default=1000,
        ge=1,
        le=1000,
        description="Max cinemas to fetch per cache refresh",
    )

    # Natural-language search / LLM
    llm_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        description="OpenAI-compatible base URL for the LLM provider",
    )
    llm_api_key: str | None = Field(
        default=None,
        description="API key for the LLM provider",
    )
    llm_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Model name to use for natural-language search",
    )
    llm_request_timeout: float = Field(
        default=60.0,
        description="Timeout in seconds for LLM requests",
    )
    llm_max_tokens: int = Field(
        default=1024,
        ge=1,
        le=4096,
        description="Max tokens for LLM response",
    )
    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="LLM sampling temperature",
    )
    llm_fallback_search_enabled: bool = Field(
        default=True,
        description="Run a fallback text search when LLM parsing fails",
    )

    @field_validator("cinetixx_sync_mandator_ids", mode="before")
    @classmethod
    def _parse_int_list(cls, value: Any) -> list[int]:
        return [int(item) for item in _parse_list_value(value)]

    @field_validator("cinetixx_sync_discovery_searches", "kinoheld_sync_cinema_ids", mode="before")
    @classmethod
    def _parse_string_list(cls, value: Any) -> list[str]:
        return [str(item).strip() for item in _parse_list_value(value) if str(item).strip()]

    @property
    def api_v1_prefix(self) -> str:
        return "/api/v1"


settings = Settings()
