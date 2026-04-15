"""Tests for GET /health endpoint."""

from __future__ import annotations

import pytest


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        r = await client.get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_health_response_shape(self, client):
        r = await client.get("/health")
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "active_sessions" in data

    @pytest.mark.asyncio
    async def test_health_active_sessions_is_string(self, client):
        data = (await client.get("/health")).json()
        # active_sessions is returned as str (see main.py)
        assert isinstance(data["active_sessions"], str)
        assert int(data["active_sessions"]) >= 0

    @pytest.mark.asyncio
    async def test_docs_returns_200(self, client):
        r = await client.get("/docs")
        assert r.status_code == 200
