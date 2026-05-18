"""Tests for /api/export endpoints (D1)."""

from __future__ import annotations

import pytest


class TestExportModel:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, authenticated_client):
        r = await authenticated_client.get("/api/export/model/doesnotexist/foo")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_trained_model_returns_400(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await authenticated_client.get(f"/api/export/model/{sid}/foo")
        assert r2.status_code == 400


class TestExportCarte:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, authenticated_client):
        r = await authenticated_client.get("/api/export/carte/doesnotexist")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_carte_returns_400(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await authenticated_client.get(f"/api/export/carte/{sid}")
        assert r2.status_code == 400


class TestExportCompteurs:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, authenticated_client):
        r = await authenticated_client.get("/api/export/compteurs/doesnotexist")
        assert r.status_code == 404


class TestExportModelsAll:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, authenticated_client):
        r = await authenticated_client.get("/api/export/models-all/doesnotexist")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_output_dir_returns_400(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await authenticated_client.get(f"/api/export/models-all/{sid}")
        assert r2.status_code == 400
