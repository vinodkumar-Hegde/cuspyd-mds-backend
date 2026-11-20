"""Backend configuration; database settings never belong in Vite."""
from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')
    database_url: str
    jwt_secret: str = Field(min_length=32)
    cors_origin: str = 'http://localhost:3000'
    upload_dir: Path = Path('uploads')
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    storage_backend: Literal['local', 's3'] = 'local'
    s3_bucket: str = ''
    s3_prefix: str = 'uploads'
    s3_region: str = ''
    aws_region: str = ''
    aws_default_region: str = ''
    s3_presign_seconds: int = Field(default=300, ge=60, le=3600)
    s3_kms_key_id: str = ''
    phone_default_region: str = 'IN'
    access_token_minutes: int = Field(default=60, ge=5, le=480)
    exam_seconds_per_question: int = Field(default=60, ge=10, le=600)
    app_env: str = 'development'
    forwarded_allow_ips: str = '127.0.0.1'

    @field_validator('forwarded_allow_ips')
    @classmethod
    def trusted_proxies(cls, value: str) -> str:
        peers = [peer.strip() for peer in value.split(',') if peer.strip()]
        for peer in peers:
            try:
                network = ip_network(peer, strict=False)
            except ValueError:
                raise ValueError('FORWARDED_ALLOW_IPS must list explicit proxy IPs or CIDRs') from None
            if network.prefixlen == 0:
                raise ValueError('Do not trust forwarded headers from all networks')
        return ','.join(peers)

    @field_validator('database_url')
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if not value.startswith('postgresql+psycopg://'):
            raise ValueError('DATABASE_URL must use postgresql+psycopg')
        return value

    @field_validator('s3_bucket', 's3_region', 'aws_region', 'aws_default_region', 's3_kms_key_id')
    @classmethod
    def trim_storage_value(cls, value: str) -> str:
        return value.strip()

    @field_validator('s3_prefix')
    @classmethod
    def storage_prefix(cls, value: str) -> str:
        value = value.strip().strip('/')
        if value and (not re.fullmatch(r'[A-Za-z0-9._/-]+', value)
                      or any(part in ('', '.', '..') for part in value.split('/'))):
            raise ValueError('S3_PREFIX must contain safe, non-empty path segments')
        return value

    @property
    def storage_region(self) -> str:
        return self.s3_region or self.aws_region or self.aws_default_region

    @model_validator(mode='after')
    def configured_storage(self):
        if self.storage_backend == 's3':
            if (not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', self.s3_bucket)
                    or any(part in self.s3_bucket for part in ('..', '.-', '-.'))
                    or re.fullmatch(r'\d+\.\d+\.\d+\.\d+', self.s3_bucket)):
                raise ValueError('Set S3_BUCKET to a valid general-purpose S3 bucket name')
            if not self.storage_region:
                raise ValueError('Set S3_REGION, AWS_REGION or AWS_DEFAULT_REGION for S3 storage')
        return self

    @property
    def origins(self) -> list[str]:
        origins = [origin.strip().rstrip('/') for origin in self.cors_origin.split(',') if origin.strip()]
        if not origins or '*' in origins:
            raise ValueError('Set CORS_ORIGIN to explicit frontend origins')
        return origins


@lru_cache
def settings() -> Settings:
    return Settings()
