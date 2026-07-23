"""Application configuration loaded from environment variables.

All settings come from the environment (or a local ``.env`` file). Never hardcode
secrets — see ``.env.example`` for the full list.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Supabase ----
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_storage_bucket: str = "documents"

    # ---- Database ----
    database_url: str = ""
    alembic_database_url: str = ""
    db_prepare_threshold: str = "none"  # "none" disables prepared statements (pooler)

    # ---- Redis / queue ----
    redis_url: str = "redis://localhost:6379/0"
    idp_queue_name: str = "idp"

    # ---- VLM (OpenAI-compatible vLLM endpoint) ----
    vlm_base_url: str = ""
    vlm_api_key: str = ""
    vlm_model: str = "Qwen2.5-VL-7B-Instruct"
    # Total context window (input + output) the served model allows. The extraction
    # stage budgets text/image chunks against this so a small-context model
    # (e.g. Qwen2-VL-2B at 2048) never overflows. Raise to match a larger server.
    vlm_max_model_len: int = 2048
    vlm_max_output_tokens: int = 768  # tokens reserved for the JSON response per call
    vlm_render_dpi: int = (
        120  # PDF→PNG DPI for the VLM (lower than OCR's 200 — legibility, not detail)
    )
    vlm_request_timeout: float = (
        90.0  # seconds per VLM HTTP call (cold Lightning endpoints are slow)
    )
    vlm_max_chunk_calls: int = 6  # hard cap on VLM calls per document (bounds cost on large docs)

    # ---- IDP tuning ----
    confidence_threshold: float = 0.7
    promote_after_n: int = 3
    vlm_max_pages: int = (
        10  # overall page ceiling per doc; chunking + vlm_max_chunk_calls bound cost
    )
    max_upload_mb: int = 50

    # ---- LLM budget gate ----
    # Per-tenant monthly VLM token cap used when tenants.llm_monthly_token_cap is NULL.
    # The docs_llm/docs_total ratio breaker from CLAUDE.md is deferred until Phase 2
    # (deterministic extraction) exists — see project memory for the rationale.
    llm_monthly_token_cap_default: int = 2_000_000

    # ---- Trash auto-retention ----
    # Global default retention window (days) used when tenants.trash_retention_days is NULL.
    trash_retention_days_default: int = 30

    # ---- App ----
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://[::1]:3000"
    sentry_dsn: str = ""
    env: str = "development"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a list (comma-separated in the env var)."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def prepare_threshold(self) -> int | None:
        """psycopg3 prepare_threshold: None disables server-side prepared statements."""
        if self.db_prepare_threshold.lower() in ("none", "off", "disable", ""):
            return None
        return int(self.db_prepare_threshold)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
