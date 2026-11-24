import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_password: str = os.environ.get("APP_PASSWORD", "")
    secret_key: str = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    currency: str = os.environ.get("CURRENCY", "EUR")
    language: str = os.environ.get("LANGUAGE", "it")
    max_concurrency: int = _int("MAX_CONCURRENCY", 4)
    max_queries: int = _int("MAX_QUERIES", 48)
    cache_ttl_seconds: int = _int("CACHE_TTL_MINUTES", 30) * 60


settings = Settings()
