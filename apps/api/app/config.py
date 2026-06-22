"""Application settings via pydantic-settings."""

from __future__ import annotations

import json
import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# JWT secrets explicitly forbidden — used as placeholders/defaults in older
# revisions or compose files. We refuse to boot on any of these.
_FORBIDDEN_JWT_SECRETS = frozenset(
    {
        "",
        "change-me",
        "change-me-in-production",
        "change-me-in-production-use-a-real-secret",
        "changeme",
        "secret",
        "default",
    }
)
_MIN_JWT_SECRET_LEN = 32


class Settings(BaseSettings):
    """All settings come from env vars or `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # -- CORS ------------------------------------------------------------------
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        """Accept JSON list or comma-separated string from env."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                return json.loads(s)
            return [x.strip() for x in s.split(",") if x.strip()]
        return v

    # -- Upload limits ---------------------------------------------------------
    MAX_UPLOAD_MB: int = 500

    # -- Training --------------------------------------------------------------
    MAX_TRAINING_MINUTES: int = 30
    # Hard cap on grid search combinations to bound CPU/memory cost. Enforced
    # in training.py before launching the worker thread (A9).
    MAX_GRID_COMBINATIONS: int = 100

    # -- TensorFlow / GPU ------------------------------------------------------
    CUDA_VISIBLE_DEVICES: str = "-1"
    TF_CPP_MIN_LOG_LEVEL: str = "3"

    # -- Workspace -------------------------------------------------------------
    WORKSPACE_ROOT: str = "/tmp/mdl_workdir"

    # -- Redis (optional) ------------------------------------------------------
    REDIS_URL: str = ""

    # -- Auth / JWT ------------------------------------------------------------
    # No default — fail-fast in _validate_jwt_secret if missing/weak/known.
    # Provide via env var or .env file. Generate with: openssl rand -hex 32
    JWT_SECRET: str = ""

    # -- Environment / deployment ---------------------------------------------
    # "production" disables /docs, /redoc, /openapi.json and tightens /metrics.
    ENVIRONMENT: str = "development"
    # CSV list (or JSON list) of IPs allowed to scrape /metrics in production.
    # Empty list means /metrics is disabled in production.
    METRICS_ALLOWED_IPS: list[str] = []

    @field_validator("METRICS_ALLOWED_IPS", mode="before")
    @classmethod
    def _parse_metrics_ips(cls, v):
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            if s.startswith("["):
                return json.loads(s)
            return [x.strip() for x in s.split(",") if x.strip()]
        return v

    # -- Monitoring ------------------------------------------------------------
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"

    # -- Session ---------------------------------------------------------------
    SESSION_TTL_SECONDS: int = 7200  # 2 hours

    @field_validator("JWT_SECRET")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        """Fail-fast at boot: refuse known placeholders and short secrets.

        Audit 01, P0-3: a default trivial secret enables JWT forgery and full
        impersonation of any user. We refuse to start if the secret is empty,
        a known placeholder, or below the 32-character minimum.
        """
        stripped = (v or "").strip()
        normalized = stripped.lower()
        if normalized in _FORBIDDEN_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET is empty or set to a known default placeholder. "
                "Generate one with `openssl rand -hex 32` and set it via the "
                "JWT_SECRET environment variable."
            )
        if "change-me" in normalized:
            raise ValueError(
                "JWT_SECRET still contains 'change-me'. Replace with a real "
                "secret generated via `openssl rand -hex 32`."
            )
        if len(stripped) < _MIN_JWT_SECRET_LEN:
            raise ValueError(
                f"JWT_SECRET is too short ({len(stripped)} chars). Minimum "
                f"is {_MIN_JWT_SECRET_LEN}. Generate one via `openssl rand -hex 32`."
            )
        return stripped

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Singleton accessor — cached after first call."""
    settings = Settings()
    # Apply TF env vars early, before any TF import
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", settings.CUDA_VISIBLE_DEVICES)
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", settings.TF_CPP_MIN_LOG_LEVEL)
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    return settings
