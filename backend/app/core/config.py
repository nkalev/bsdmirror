"""
Configuration settings for BSD Mirrors API.

Uses pydantic-settings for environment variable management.
"""
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    #
    # GIT_SHA/BUILD_DATE come from the environment backend/Dockerfile bakes in
    # (ARG GIT_SHA / ARG BUILD_DATE, promoted to ENV so they survive into the
    # running container) rather than a hand-maintained constant. This field
    # used to hold a hardcoded semantic-version string, one version number
    # higher than a matching constant frontend/public/index.html hardcoded in
    # its footer; neither had ever been bumped, and they already disagreed.
    # Defaults are "unknown", not a placeholder that could pass for a real
    # build (e.g. a fake-looking 0.0.0) -- a bare `docker build` with no
    # --build-arg, which is what anyone building this image by hand gets,
    # must not look like a deployed version.
    GIT_SHA: str = Field(default="unknown")
    BUILD_DATE: str = Field(default="unknown")
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    @property
    def VERSION(self) -> str:
        """What this running process reports as its version everywhere:
        settings.VERSION (this property), the FastAPI app's own `version=`,
        the root endpoint, and /api/health and /api/health/detailed. One
        property, so there is exactly one place either half can come from --
        see the class docstring above.
        """
        return f"{self.GIT_SHA}-{self.BUILD_DATE}"
    
    # Database
    POSTGRES_HOST: str = Field(default="postgres")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DB: str = Field(default="bsdmirrors")
    POSTGRES_USER: str = Field(default="bsdmirrors")
    POSTGRES_PASSWORD: str = Field(...)
    
    @property
    def DATABASE_URL(self) -> str:
        """Construct async PostgreSQL connection URL."""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    # Redis
    REDIS_HOST: str = Field(default="redis")
    REDIS_PORT: int = Field(default=6379)
    REDIS_PASSWORD: str = Field(...)
    
    @property
    def REDIS_URL(self) -> str:
        """Construct Redis connection URL."""
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
    
    # Security
    SECRET_KEY: str = Field(...)
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_EXPIRY_HOURS: int = Field(default=8)
    
    # Admin user (created on first run)
    ADMIN_USERNAME: str = Field(default="admin")
    ADMIN_PASSWORD: str = Field(...)
    
    # CORS
    CORS_ORIGINS: List[str] = Field(default=["http://localhost:3000", "http://localhost:8080"])
    
    # Mirror paths
    MIRROR_DATA_PATH: str = Field(default="/data/mirrors")
    
    # Database pool
    DB_POOL_SIZE: int = Field(default=10)
    DB_MAX_OVERFLOW: int = Field(default=20)

    # Rate limiting
    API_RATE_LIMIT: int = Field(default=10)
    API_RATE_BURST: int = Field(default=20)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
