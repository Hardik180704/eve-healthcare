from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "EVE Healthcare API"
    environment: str = "development"
    debug: bool = True

    # Database
    database_url: str = "postgresql+psycopg://eve:eve_password@localhost:5432/eve_healthcare"

    # Security
    jwt_secret_key: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Payments
    payment_gateway_url: str = "http://localhost:9999"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
