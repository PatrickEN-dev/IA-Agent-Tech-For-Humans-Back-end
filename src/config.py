from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-secret-key-change-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    jwt_secret_key: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 15

    use_langchain: bool = False
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 100
    llm_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Tempo maximo esperando o LLM antes de cair no fallback por regras/template.
    llm_intent_timeout_seconds: float = 2.5
    llm_humanize_timeout_seconds: float = 4.0
    intent_cache_max_size: int = 500

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    exchange_api_url: str = "https://api.exchangerate-api.com/v4/latest"
    exchange_api_key: str | None = None
    exchange_api_timeout_seconds: float = 4.0

    log_level: str = "INFO"
    # JSON em produção (filtrável por request_id), texto alinhado em desenvolvimento.
    json_logs: bool = False

    # Origens permitidas pelo CORS. "*" só faz sentido enquanto a API é pública e sem
    # cookie; em produção com credenciais isso vira a lista de domínios do front.
    cors_origins: str = "*"

    # CSVs continuam sendo a fonte do seed (o desafio os define); o banco é o que roda.
    data_dir: Path = Path("src/data")

    database_url: str = "sqlite+aiosqlite:///./data/banco_agil.db"
    # Recria o banco a partir do seed a cada boot. Verdadeiro na demo (dados sempre
    # limpos, e o disco do Render gratuito é efêmero de qualquer jeito).
    demo_reset_on_start: bool = True

    # Liga as personas de demonstração e o auto-cadastro público.
    demo_mode: bool = True
    demo_persona_count: int = 4

    # Auto-cadastro: score inicial de quem se cadastra sem entrevista.
    signup_enabled: bool = True
    signup_initial_score: int = 500
    signup_min_age_years: int = 18

    # Consulta de CEP (BrasilAPI é pública e não exige chave).
    address_api_url: str = "https://brasilapi.com.br/api/cep/v2"
    address_api_timeout_seconds: float = 4.0
    # Provedor de verificação de CPF: "mock" (offline, determinístico) ou "serpro".
    cpf_provider: Literal["mock", "serpro"] = "mock"
    serpro_api_url: str = "https://gateway.apiserpro.serpro.gov.br/consulta-cpf-df/v1"
    serpro_api_token: str | None = None
    cpf_provider_timeout_seconds: float = 4.0

    rate_limit_enabled: bool = True
    rate_limit_chat: str = "60/minute"
    rate_limit_auth: str = "10/minute"
    rate_limit_signup: str = "5/minute"

    max_auth_attempts: int = 3
    # Janela de bloqueio por CPF no endpoint /triage/authenticate apos esgotar as tentativas.
    auth_lockout_minutes: int = 15
    session_ttl_minutes: int = 30
    max_conversation_history: int = 20
    # Mensagens maiores que isso nao sao processadas (evita custo de LLM e historico inflado).
    max_message_length: int = 2000

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

    def llm_enabled(self) -> bool:
        return self.use_langchain and self.has_llm_api_key()

    def uses_default_jwt_secret(self) -> bool:
        return self.jwt_secret_key == DEFAULT_JWT_SECRET

    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return origins or ["*"]

    def cpf_provider_enabled(self) -> bool:
        """O provedor real só entra em cena com token; sem ele, cai no mock."""
        if self.cpf_provider == "serpro":
            return bool(self.serpro_api_token)
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()
