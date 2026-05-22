"""Application settings loaded from environment variables.

All configuration is centralized here to avoid scattered hardcoded values.
Environment variables are prefixed with ``DOCSIFER_`` (see ``.env.example``).
"""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized, env-driven application settings."""

    model_config = SettingsConfigDict(
        env_prefix="DOCSIFER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------------
    # General
    # ---------------------------------------------------------------------
    app_name: str = "Docsifer"
    app_version: str = "1.1.0"
    environment: Literal["development", "staging", "production"] = "production"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True

    # ---------------------------------------------------------------------
    # HTTP / API
    # ---------------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    cors_allow_credentials: bool = False  # safe with origins=["*"]
    request_timeout_sec: int = 55  # < HF Spaces 60s timeout
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB free-tier default
    gzip_min_size: int = 1024
    enable_security_headers: bool = True

    # ---------------------------------------------------------------------
    # Concurrency / resources
    # ---------------------------------------------------------------------
    max_concurrent_conversions: int = 2  # tuned for 2 vCPU
    max_queue_depth: int = 10
    max_per_ip_concurrent: int = 1
    worker_pool_size: int = 4  # ThreadPoolExecutor for sync work
    min_free_memory_mb: int = 512
    min_free_disk_mb: int = 256
    memory_watchdog_pct: float = 90.0
    memory_watchdog_interval_sec: int = 30
    enable_memory_watchdog: bool = False  # disabled by default in dev
    disk_cleanup_interval_sec: int = 600
    disk_cleanup_ttl_sec: int = 3600

    # ---------------------------------------------------------------------
    # Conversion
    # ---------------------------------------------------------------------
    token_model: str = "gpt-4o"
    default_openai_base_url: str = "https://api.openai.com/v1"
    default_openai_model: str = "gpt-4o-mini"
    openai_request_timeout_sec: float = 60.0
    openai_connect_timeout_sec: float = 10.0
    openai_max_retries: int = 2

    # LLM client cache
    llm_cache_max_size: int = 16
    llm_cache_ttl_sec: int = 600

    # Allowed file extensions (lower-case, with leading dot)
    allowed_extensions: list[str] = Field(
        default_factory=lambda: [
            ".html",
            ".htm",
            ".zip",
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".csv",
            ".tsv",
            ".ipynb",
            ".msg",
            ".xml",
            ".docx",
            ".doc",
            ".json",
            ".pptx",
            ".ppt",
            ".xls",
            ".xlsx",
            ".pdf",
            ".mp3",
            ".wav",
            ".m4a",
            ".txt",
            ".md",
            ".rtf",
        ]
    )

    # ---------------------------------------------------------------------
    # SSRF / URL fetch guard
    # ---------------------------------------------------------------------
    url_allow_private_networks: bool = False
    url_allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])

    # ---------------------------------------------------------------------
    # Analytics / Redis
    #
    # ``redis_url`` is empty by default so fresh deployments (HF Spaces, local
    # dev) start in in-memory analytics mode out of the box. Set
    # ``DOCSIFER_REDIS_URL`` (and ``DOCSIFER_REDIS_TOKEN`` for Upstash) to
    # opt into persistent analytics.
    # ---------------------------------------------------------------------
    redis_url: str = ""
    redis_token: str | None = None
    analytics_enabled: bool = True
    analytics_sync_interval_sec: int = 1800  # 30 min
    analytics_max_retries: int = 5
    analytics_label: str = "docsifer"

    @property
    def analytics_persistent(self) -> bool:
        """True when a real (non-empty, non-localhost) Redis URL is configured."""
        if not self.analytics_enabled:
            return False
        url = (self.redis_url or "").strip()
        if not url:
            return False
        return True

    # ---------------------------------------------------------------------
    # Quotas (anonymous, BYOK, authenticated)
    # ---------------------------------------------------------------------
    quota_enabled: bool = False  # enable when slowapi/redis is configured
    quota_anon_rph: int = 10
    quota_anon_rpd: int = 50
    quota_byok_rph: int = 60
    quota_byok_rpd: int = 500
    quota_auth_keys: list[str] = Field(default_factory=list)

    # ---------------------------------------------------------------------
    # Observability
    # ---------------------------------------------------------------------
    enable_prometheus: bool = False
    sentry_dsn: str | None = None

    # ---------------------------------------------------------------------
    # Filesystem
    # ---------------------------------------------------------------------
    tmp_dir: Path = Field(default_factory=lambda: Path(tempfile.gettempdir()))

    # ---------------------------------------------------------------------
    # Validators
    # ---------------------------------------------------------------------
    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def _normalize_exts(cls, v: object) -> list[str]:
        if isinstance(v, str):
            v = [item.strip() for item in v.split(",") if item.strip()]
        if not isinstance(v, list):
            raise TypeError("allowed_extensions must be a list or comma-separated string")
        return [e.lower() if e.startswith(".") else f".{e.lower()}" for e in v]

    @field_validator("cors_origins", "url_allowed_schemes", "quota_auth_keys", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return list(v) if v else []

    # ---------------------------------------------------------------------
    # Convenience properties
    # ---------------------------------------------------------------------
    @property
    def cors_allow_credentials_safe(self) -> bool:
        """``allow_credentials`` is invalid together with ``allow_origins=['*']``."""
        if "*" in self.cors_origins:
            return False
        return self.cors_allow_credentials

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide singleton ``Settings`` instance."""
    return Settings()
