from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEV_SECRET = "dev-secret-key-change-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["dev", "staging", "prod"] = "dev"
    jwt_secret_key: str = _DEV_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 15

    use_langchain: bool = False
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 120
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 8

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    exchange_api_url: str = "https://api.exchangerate-api.com/v4/latest"
    exchange_api_key: str | None = None
    exchange_cache_ttl_seconds: int = 300

    log_level: str = "INFO"
    cors_origins: list[str] = ["*"]

    data_dir: Path = Path("src/data")
    max_auth_attempts: int = 3

    @property
    def clients_csv_path(self) -> Path:
        return self.data_dir / "clientes.csv"

    @property
    def score_limits_csv_path(self) -> Path:
        return self.data_dir / "score_limite.csv"

    @property
    def limit_requests_csv_path(self) -> Path:
        return self.data_dir / "solicitacoes_aumento_limite.csv"

    def has_llm_api_key(self) -> bool:
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return bool(self.anthropic_api_key)

    def validate_for_boot(self) -> None:
        """Loud warnings when running with unsafe defaults.

        Called at app startup. In production with the dev secret we refuse
        to start; in other environments we log a warning.
        """
        if self.jwt_secret_key == _DEV_SECRET:
            if self.environment == "prod":
                raise RuntimeError(
                    "JWT_SECRET_KEY is still the development default — "
                    "refusing to start in production."
                )
            logger.warning(
                "JWT_SECRET_KEY is using the development default. "
                "Set a strong secret in .env before going to production."
            )
        if self.environment == "prod" and self.cors_origins == ["*"]:
            logger.warning(
                "CORS_ORIGINS=['*'] in production — restrict to your "
                "frontend's domain."
            )


_settings_override: Settings | None = None


def get_settings() -> Settings:
    """Return the active Settings instance.

    A test (or any caller) can swap the global via `set_settings_override`.
    No lru_cache: instances created at module import in earlier versions
    could not be refreshed during tests.
    """
    return _settings_override or _default()


def set_settings_override(settings: Settings | None) -> None:
    global _settings_override
    _settings_override = settings


def _default() -> Settings:
    global _default_cached
    if _default_cached is None:
        _default_cached = Settings()
    return _default_cached


_default_cached: Settings | None = None
