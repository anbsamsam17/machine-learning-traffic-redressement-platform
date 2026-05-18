"""End-to-end auth flow tests (D2 + A1 + A4).

Covers the regression "auth obligatoire sur tous les routers metier" plus
the JWT_SECRET fail-fast guarantee.
"""

from __future__ import annotations

import os
import secrets

import pytest
from pydantic import ValidationError


class TestRegisterLogin:
    @pytest.mark.asyncio
    async def test_register_returns_201_with_user_id(self, client):
        email = f"reg+{secrets.token_hex(4)}@example.com"
        r = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "supersecret"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "user_id" in body
        assert body["email"] == email
        assert len(body["user_id"]) == 32  # uuid4 hex

    @pytest.mark.asyncio
    async def test_register_rejects_short_password(self, client):
        r = await client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "abc"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_register_duplicate_returns_409(self, client):
        email = f"dup+{secrets.token_hex(4)}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "supersecret"},
        )
        r = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "supersecret"},
        )
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_login_returns_jwt_token(self, client):
        email = f"login+{secrets.token_hex(4)}@example.com"
        password = "supersecret123"
        r = await client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        assert r.status_code == 201

        r = await client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"

        # Token should be a decodable JWT (header.payload.signature, base64url)
        token = body["access_token"]
        assert token.count(".") == 2

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self, client):
        email = f"wp+{secrets.token_hex(4)}@example.com"
        await client.post(
            "/api/auth/register",
            json={"email": email, "password": "rightpass"},
        )
        r = await client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrongpass"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_login_unknown_user_returns_401(self, client):
        r = await client.post(
            "/api/auth/login",
            json={"email": "noone@nowhere.example", "password": "whatever"},
        )
        assert r.status_code == 401


class TestProtectedRoutes:
    """A1: any business endpoint must answer 401 without a token."""

    @pytest.mark.asyncio
    async def test_upload_without_token_returns_401(self, client, csv_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        assert r.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_upload_with_invalid_token_returns_401(self, client, csv_content):
        client.headers.update({"Authorization": "Bearer notavalidtoken"})
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_with_valid_token_succeeds(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        # 200 (existing handler) or 201 — both prove auth passed.
        assert r.status_code in (200, 201), r.text

    @pytest.mark.asyncio
    async def test_me_returns_user_when_authenticated(self, authenticated_client):
        r = await authenticated_client.get("/api/auth/me")
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == authenticated_client.user_id
        assert body["email"] == authenticated_client.user_email

    @pytest.mark.asyncio
    async def test_me_returns_401_without_token(self, client):
        r = await client.get("/api/auth/me")
        assert r.status_code in (401, 403)


class TestPublicRoutes:
    @pytest.mark.asyncio
    async def test_health_is_public(self, client):
        r = await client.get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_register_is_public(self, client):
        # The endpoint must be reachable without a token (otherwise nobody
        # could ever sign up).
        r = await client.post(
            "/api/auth/register",
            json={"email": f"pub+{secrets.token_hex(4)}@example.com", "password": "abcdefgh"},
        )
        assert r.status_code in (201, 409)

    @pytest.mark.asyncio
    async def test_login_is_public(self, client):
        # Wrong credentials still proves the endpoint runs without a token.
        r = await client.post(
            "/api/auth/login",
            json={"email": "x@y.example", "password": "irrelevant"},
        )
        assert r.status_code == 401  # never 401-from-Depends


class TestJWTSecretFailFast:
    """A4: refuse to load Settings on weak / missing / placeholder secrets."""

    def test_empty_secret_raises(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("JWT_SECRET", "")
        with pytest.raises(ValidationError):
            Settings()

    def test_short_secret_raises(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("JWT_SECRET", "abc123")
        with pytest.raises(ValidationError):
            Settings()

    def test_placeholder_change_me_raises(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("JWT_SECRET", "change-me-in-production")
        with pytest.raises(ValidationError):
            Settings()

    def test_placeholder_substring_change_me_raises(self, monkeypatch):
        from app.config import Settings

        # Even if the user pads to >= 32 chars, "change-me" anywhere is refused.
        monkeypatch.setenv("JWT_SECRET", "change-me" + "x" * 40)
        with pytest.raises(ValidationError):
            Settings()

    def test_real_random_secret_accepted(self, monkeypatch):
        from app.config import Settings

        good = secrets.token_hex(32)
        monkeypatch.setenv("JWT_SECRET", good)
        s = Settings()
        assert s.JWT_SECRET == good
