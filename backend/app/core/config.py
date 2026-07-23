"""Application configuration loaded from environment variables.

All settings come from the environment (or a local ``.env`` file). Never hardcode
secrets — see ``.env.example`` for the full list.
"""

# functools.lru_cache lets us memoize get_settings() so the .env file is only
# ever parsed once per process, not on every single call.
from functools import lru_cache

# pydantic-settings gives us a typed, validated settings object that reads
# straight from environment variables / a .env file instead of hand-rolled
# os.environ.get() calls scattered everywhere.
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings."""

    # model_config tells pydantic-settings HOW to load these fields.
    model_config = SettingsConfigDict(
        env_file=".env",  # look for a local .env file next to where the app runs
        env_file_encoding="utf-8",  # read that file as UTF-8 text
        extra="ignore",  # ignore any .env keys that don't match a field below (don't error)
        case_sensitive=False,  # SUPABASE_URL and supabase_url are treated the same
    )

    # ---- Supabase ----
    supabase_url: str = ""  # base URL of the Supabase project, e.g. https://xxxx.supabase.co
    supabase_anon_key: str = ""  # public, safe-for-frontend anonymous API key
    supabase_service_role_key: str = (
        ""  # PRIVATE admin key — backend only, full access, never expose
    )
    supabase_jwt_secret: str = ""  # secret used to verify HS256-signed Supabase JWTs
    supabase_storage_bucket: str = "documents"  # name of the Storage bucket holding uploaded files

    # ---- Database ----
    database_url: str = ""  # connection string the live API/worker use (pooled, restricted role)
    alembic_database_url: str = ""  # connection string migrations use (direct, superuser)
    db_prepare_threshold: str = "none"  # "none" disables prepared statements (pooler)

    # ---- Redis / queue ----
    redis_url: str = "redis://localhost:6379/0"  # where Redis (the job queue backend) lives
    idp_queue_name: str = "idp"  # name of the RQ queue the worker listens on

    # ---- VLM (OpenAI-compatible vLLM endpoint) ----
    vlm_base_url: str = ""  # HTTP endpoint of the self-hosted vision-language model server
    vlm_api_key: str = ""  # API key for that endpoint, if it requires one
    vlm_model: str = "Qwen2.5-VL-7B-Instruct"  # which model name to request from the endpoint
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
    confidence_threshold: float = 0.7  # minimum confidence for a VLM extraction to be "accepted"
    promote_after_n: int = 3  # how many accepted examples before a template is "promoted"
    vlm_max_pages: int = (
        10  # overall page ceiling per doc; chunking + vlm_max_chunk_calls bound cost
    )
    max_upload_mb: int = 50  # largest single file the API will accept, in megabytes

    # ---- LLM budget gate ----
    # Per-tenant monthly VLM token cap used when tenants.llm_monthly_token_cap is NULL.
    # The docs_llm/docs_total ratio breaker from CLAUDE.md is deferred until Phase 2
    # (deterministic extraction) exists — see project memory for the rationale.
    llm_monthly_token_cap_default: int = 2_000_000

    # ---- Trash auto-retention ----
    # Global default retention window (days) used when tenants.trash_retention_days is NULL.
    trash_retention_days_default: int = 30

    # ---- App ----
    # Comma-separated list of origins the browser is allowed to call the API from (CORS).
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://[::1]:3000"
    sentry_dsn: str = ""  # Sentry error-reporting DSN; empty string = Sentry stays off
    env: str = "development"  # "development" or "production" — gates docs/CSP/error-detail behavior

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a list (comma-separated in the env var)."""
        # Split on commas, strip whitespace from each entry, and drop any empty
        # strings that result from a trailing comma or blank env value.
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def prepare_threshold(self) -> int | None:
        """psycopg3 prepare_threshold: None disables server-side prepared statements."""
        # Several spellings of "off" are accepted so the .env file can be written
        # however the operator finds most natural — all of them mean the same thing.
        if self.db_prepare_threshold.lower() in ("none", "off", "disable", ""):
            return None
        # Anything else is parsed as an actual integer threshold value.
        return int(self.db_prepare_threshold)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    # @lru_cache with no arguments means this only ever runs once per process —
    # every subsequent call returns the exact same Settings object instantly,
    # instead of re-reading and re-parsing the .env file every time.
    return Settings()


# Module-level singleton — every other file in the app imports THIS object
# directly (from app.core.config import settings) rather than calling
# get_settings() itself, so there's exactly one settings instance app-wide.
settings = get_settings()
