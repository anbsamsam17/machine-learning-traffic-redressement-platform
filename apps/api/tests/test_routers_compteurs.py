"""Tests for /api/compteurs endpoints (D1)."""

from __future__ import annotations

import pytest


class TestCompteursGenerate:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, client):
        r = await client.post(
            "/api/compteurs/generate",
            json={
                "session_id": "nonexistent",
                "column_mapping": {},
            },
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_happy_path_generates_geojson(self, client, csv_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        sid = r.json()["session_id"]

        r2 = await client.post(
            "/api/compteurs/generate",
            json={
                "session_id": sid,
                "column_mapping": {
                    "Identifiant du Poste / Section": "Identifiant",
                    "TMJA Tous Vehicules (veh/jour)": "TMJAFCDTV",
                    "TMJA Poids Lourds (veh/jour)": "TMJAFCDPL",
                    "Type de capteur": "Type",
                },
                "missing_columns_default": {"Sens de comptage": "B"},
                "missing_columns_action": {
                    "Annee": "default",
                    "Nom de la Commune": "default",
                    "RD": "default",
                    "PRD": "default",
                },
            },
        )
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["session_id"] == sid
        assert data["geojson_feature_count"] >= 0
        assert "stats" in data


class TestCompteursDownload:
    @pytest.mark.asyncio
    async def test_download_before_generate_returns_400(self, client, csv_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await client.get(f"/api/compteurs/download/{sid}")
        assert r2.status_code == 400

    @pytest.mark.asyncio
    async def test_download_invalid_session_404(self, client):
        r = await client.get("/api/compteurs/download/doesnotexist")
        assert r.status_code == 404
