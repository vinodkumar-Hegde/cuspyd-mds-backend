"""Backend configuration; database settings never belong in Vite."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')
    database_url: str
    jwt_secret: str = Field(min_length=32)
    cors_origin: str = 'http://localhost:3000'
    upload_dir: Path = Path('uploads')
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    phone_default_region: str = 'IN'
    access_token_minutes: int = Field(default=60, ge=5, le=480)
    exam_seconds_per_question: int = Field(default=60, ge=10, le=600)
    app_env: str = 'development'

    @field_validator('database_url')
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if not value.startswith('postgresql+psycopg://'):
            raise ValueError('DATABASE_URL must use postgresql+psycopg')
        return value

    @property
    def origins(self) -> list[str]:
        origins = [origin.strip().rstrip('/') for origin in self.cors_origin.split(',') if origin.strip()]
        if not origins or '*' in origins:
            raise ValueError('Set CORS_ORIGIN to explicit frontend origins')
        return origins


@lru_cache
def settings() -> Settings:
    return Settings()
