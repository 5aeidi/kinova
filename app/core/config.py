"""Application configuration loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def api_v1_prefix(self) -> str:
        return "/api/v1"


settings = Settings()
