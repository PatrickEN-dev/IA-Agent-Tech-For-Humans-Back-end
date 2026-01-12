from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    jwt_secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 15

    use_langchain: bool = False
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 100
    llm_model: str = "gpt-4o-mini"  # 85 tokens/s, 60% mais barato que gpt-3.5

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    exchange_api_url: str = "https://api.exchangerate-api.com/v4/latest"
    exchange_api_key: str | None = None

    log_level: str = "INFO"

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
        elif self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
