"""Settings — reads .env. Local-first, no Docker required.

Setup v0.1: the database is REAL PostgreSQL. The app creates the
tables at startup (lifespan in main.py) and scripts/seed.py loads
realistic synthetic data. There is no in-memory / SQLite fallback:
if PostgreSQL is unreachable, /health honestly reports the database
as unavailable.

Defaults are local fallbacks for Fahad's laptop (BIOS password-locked,
VT-x disabled, so Docker Desktop cannot run):
- DATABASE_URL: local PostgreSQL (database almadar_agent, created by setup).
- OLLAMA_HOST: optional; absent = the agent is not wired yet (Sprint 2).
"""
import os

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Staging/production load their own file: AMH_ENV_FILE=.env.staging.
    # Default is the dev .env (or the built-in defaults when no file
    # exists, which is how the dev server currently runs).
    model_config = SettingsConfigDict(
        env_file=os.environ.get("AMH_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Al Madar Holding — Enterprise AI Agent"
    service: str = "almadar-ai-agent"
    version: str = "0.9.0"
    environment: str = "development"
    # DEBUG is forced off in production (validate_production_settings).
    debug: bool = False

    export_dir: str = "data/exports"
    upload_dir: str = "data/uploads"
    max_upload_mb: int = 10
    # n8n webhook shared secret. Empty = the webhook is disabled and
    # returns 503 (never an unauthenticated trigger). Set a long random
    # value in .env to enable it. The documented name is
    # AMH_N8N_WEBHOOK_SECRET (pydantic-settings reads only the first
    # alias choice from the environment; the bare field name does not
    # load from env, which is why the alias is ordered this way).
    n8n_webhook_secret: str = Field(
        default="",
        validation_alias=AliasChoices("AMH_N8N_WEBHOOK_SECRET", "n8n_webhook_secret"),
    )
    # APScheduler in-process jobs. Staging runs with the scheduler OFF
    # (jobs stay visible and manual-only) so staging never fires a
    # scheduled run against the staging database on its own.
    scheduler_enabled: bool = True
    # Monitoring alert checks (every 5 minutes, in-process scheduler).
    # ON in production only — staging/dev default OFF so a stale
    # staging database never raises alerts nobody is watching.
    monitoring_alerts_enabled: bool = False

    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/almadar_agent"
    jwt_secret: str = "CHANGE-ME-SET-A-STRONG-SECRET-IN-.env"
    ollama_host: str = "http://127.0.0.1:11434"
    supervisor_model: str = "llama3.1:8b"
    subagent_model: str = "qwen2.5:7b"

    api_port: int = 8100
    web_port: int = 3100
    cors_origins: str = "http://localhost:3100,http://127.0.0.1:3100"

    confidence_threshold: float = 0.70
    max_steps_per_run: int = 15
    max_tool_retries: int = 3
    max_run_seconds: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def demo_accounts_enabled(self) -> bool:
        # Demo accounts exist only outside production; the login
        # endpoint also refuses them when environment == "production".
        return self.environment != "production"


settings = Settings()


def validate_production_settings() -> None:
    """Fail fast at startup in production — never start half-secured.

    Called from the app lifespan. Raises RuntimeError (the server does
    not start) when: the JWT secret is weak or a placeholder, or any
    CORS origin is a wildcard. DEBUG is forced off in production even
    if the env file says otherwise.
    """
    if settings.environment != "production":
        return
    settings.debug = False
    secret = settings.jwt_secret
    if secret in ("", "CHANGE-ME-SET-A-STRONG-SECRET-IN-.env", "change-me") or len(secret) < 32:
        raise RuntimeError(
            "Refusing to start in production with a weak JWT secret. "
            "Set a strong JWT_SECRET (32+ characters) in .env.production."
        )
    if "*" in settings.cors_origin_list:
        raise RuntimeError(
            "Refusing to start in production with wildcard CORS. "
            "Set CORS_ORIGINS to the production origin only."
        )
