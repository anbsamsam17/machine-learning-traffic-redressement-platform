"""Celery application configuration."""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "mdl_redressement",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    worker_concurrency=2,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=7200,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)

celery_app.autodiscover_tasks(["app"])
