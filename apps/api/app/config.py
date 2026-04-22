"""Application settings via pydantic-settings."""

from __future__ import annotations

import json
import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # -- TensorFlow / GPU ------------------------------------------------------
    CUDA_VISIBLE_DEVICES: str = "-1"
    TF_CPP_MIN_LOG_LEVEL: str = "3"

    # -- Workspace -------------------------------------------------------------
    WORKSPACE_ROOT: str = "/tmp/mdl_workdir"

    # -- Redis (optional) ------------------------------------------------------
    REDIS_URL: str = ""

    # -- Auth / JWT ------------------------------------------------------------
    JWT_SECRET: str = "change-me-in-production-use-a-real-secret"

    # -- Monitoring ------------------------------------------------------------
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"

    # -- Session ---------------------------------------------------------------
    SESSION_TTL_SECONDS: int = 7200  # 2 hours

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Singleton accessor — cached after first call."""
    settings = Settings()
    # Apply TF env vars early, before any TF import
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", settings.CUDA_VISIBLE_DEVICES)
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", settings.TF_CPP_MIN_LOG_LEVEL)
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    return settings
