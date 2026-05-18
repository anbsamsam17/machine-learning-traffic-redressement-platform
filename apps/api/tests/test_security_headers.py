"""Security headers + sanitized error responses + training guardrails.

Covers A6 (rate-limit module), A7 (security headers middleware),
A8 (sanitized 500 + minimal /health) and A9 (training_guard helpers).
"""

from __future__ import annotations

import pytest


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_hsts_header_present(self, client):
        r = await client.get("/health")
        assert r.headers.get("strict-transport-security") is not None
        assert "max-age=63072000" in r.headers["strict-transport-security"]
        assert "includeSubDomains" in r.headers["strict-transport-security"]

    @pytest.mark.asyncio
    async def test_x_content_type_options_nosniff(self, client):
        r = await client.get("/health")
        assert r.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options_deny(self, client):
        r = await client.get("/health")
        assert r.headers.get("x-frame-options") == "DENY"

    @pytest.mark.asyncio
    async def test_referrer_policy(self, client):
        r = await client.get("/health")
        assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_csp_present_with_self(self, client):
        r = await client.get("/health")
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp

    @pytest.mark.asyncio
    async def test_permissions_policy(self, client):
        r = await client.get("/health")
        pp = r.headers.get("permissions-policy", "")
        assert "geolocation=()" in pp
        assert "camera=()" in pp
        assert "microphone=()" in pp

    @pytest.mark.asyncio
    async def test_headers_on_401_responses(self, client):
        # A1 — protected route without auth → 401 must still carry headers.
        r = await client.get("/api/auth/me")
        assert r.headers.get("strict-transport-security") is not None
        assert r.headers.get("x-frame-options") == "DENY"


class TestSanitizedErrorResponse:
    @pytest.mark.asyncio
    async def test_404_does_not_leak_internals(self, client):
        r = await client.get("/this/route/never/exists")
        assert r.status_code == 404
        body = r.json()
        # FastAPI default 404 body: {"detail": "Not Found"} — no traceback.
        assert "Traceback" not in (body.get("detail") or "")

    @pytest.mark.asyncio
    async def test_request_id_header_present(self, client):
        r = await client.get("/health")
        # RequestIDMiddleware always injects a request id
        assert r.headers.get("x-request-id") is not None
        assert len(r.headers["x-request-id"]) >= 8


class TestHealth:
    """A8: /health must be minimal in production, verbose in dev."""

    @pytest.mark.asyncio
    async def test_health_returns_status_ok(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestDocsExposure:
    @pytest.mark.asyncio
    async def test_docs_reachable_in_dev(self, client):
        # Test env forces ENVIRONMENT=development → /docs is reachable.
        r = await client.get("/docs")
        assert r.status_code == 200


class TestTrainingGuard:
    """A9: per-user lock + grid cap + deadline."""

    def test_acquire_training_slot_blocks_concurrent_runs(self):
        from app.training_guard import acquire_training_slot
        from fastapi import HTTPException

        user_id = "guard_user_a"
        with acquire_training_slot(user_id):
            with pytest.raises(HTTPException) as exc:
                with acquire_training_slot(user_id):
                    pass
            assert exc.value.status_code == 409

    def test_acquire_training_slot_releases_on_exit(self):
        from app.training_guard import acquire_training_slot

        user_id = "guard_user_b"
        with acquire_training_slot(user_id):
            pass
        # Can re-acquire immediately
        with acquire_training_slot(user_id):
            pass

    def test_different_users_dont_block_each_other(self):
        from app.training_guard import acquire_training_slot

        with acquire_training_slot("guard_user_c"):
            with acquire_training_slot("guard_user_d"):
                pass

    def test_enforce_grid_cap_passes_under_limit(self, monkeypatch):
        from app.training_guard import enforce_grid_cap

        monkeypatch.setattr(
            "app.training_guard.get_settings",
            lambda: type("S", (), {"MAX_GRID_COMBINATIONS": 100})(),
        )
        enforce_grid_cap(50)  # should not raise

    def test_enforce_grid_cap_raises_over_limit(self, monkeypatch):
        from app.training_guard import enforce_grid_cap
        from fastapi import HTTPException

        monkeypatch.setattr(
            "app.training_guard.get_settings",
            lambda: type("S", (), {"MAX_GRID_COMBINATIONS": 100})(),
        )
        with pytest.raises(HTTPException) as exc:
            enforce_grid_cap(500)
        assert exc.value.status_code == 400
        assert "depasse" in exc.value.detail or "500" in exc.value.detail

    def test_training_deadline_fires_after_window(self):
        from datetime import datetime, timedelta, timezone

        from app.training_guard import TrainingDeadline

        start = datetime.now(timezone.utc) - timedelta(minutes=120)
        d = TrainingDeadline(started_at=start, max_minutes=30)
        assert d.should_stop()

    def test_training_deadline_not_fired_inside_window(self):
        from datetime import datetime, timezone

        from app.training_guard import TrainingDeadline

        d = TrainingDeadline(started_at=datetime.now(timezone.utc), max_minutes=30)
        assert not d.should_stop()


class TestRateLimitModule:
    """A6: limiter exposed via app.rate_limit (no import cycle)."""

    def test_limiter_singleton_importable(self):
        from app.rate_limit import (
            limit_auth_login,
            limit_auth_register,
            limit_carte_generate,
            limit_training_start,
            limit_upload,
            limiter,
        )

        # All factories must return a callable decorator.
        for factory in (
            limit_auth_login,
            limit_auth_register,
            limit_upload,
            limit_training_start,
            limit_carte_generate,
        ):
            decorator = factory()
            assert callable(decorator)

        # The singleton is wired into the app state.
        from app.main import app

        assert app.state.limiter is limiter
