"""Tests for /api/evaluation endpoints (D1)."""

from __future__ import annotations

import pytest


class TestUploadValidation:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/evaluation/upload-validation",
            files={"file": ("val.csv", csv_content, "text/csv")},
            data={"session_id": "nonexistent"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_happy_path_csv(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await authenticated_client.post(
            "/api/evaluation/upload-validation",
            files={"file": ("val.csv", csv_content, "text/csv")},
            data={"session_id": sid},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["status"] == "ok"
        assert data["rows"] == 3


class TestRunEvaluation:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, authenticated_client):
        r = await authenticated_client.post(
            "/api/evaluation/run",
            json={"session_id": "doesnotexist"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_trained_model_returns_400(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        # No model, no model_dir, no session-stored model -> 400
        r2 = await authenticated_client.post(
            "/api/evaluation/run",
            json={"session_id": sid},
        )
        assert r2.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_model_dir_returns_404(self, authenticated_client, csv_content, tmp_path):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await authenticated_client.post(
            "/api/evaluation/run",
            json={
                "session_id": sid,
                "model_name": "doesnotexist",
                "model_dir": str(tmp_path),
            },
        )
        assert r2.status_code in (400, 404)


class TestReport:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, authenticated_client):
        r = await authenticated_client.get("/api/evaluation/report/doesnotexist")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_evaluation_returns_400(self, authenticated_client, csv_content):
        r = await authenticated_client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await authenticated_client.get(f"/api/evaluation/report/{sid}")
        assert r2.status_code == 400


class TestDownloadModel:
    @pytest.mark.asyncio
    async def test_invalid_model_dir_returns_4xx(self, authenticated_client, tmp_path):
        """T2: A5 plugue validate_path qui peut renvoyer 400 (path traversal /
        path hors session root) ou 404 (model_dir manquant). Les deux sont
        valides ; l'important est que ce ne soit pas 200 ou 500."""
        r = await authenticated_client.get(
            "/api/evaluation/download-model",
            params={"model_name": "nope", "model_dir": str(tmp_path / "missing")},
        )
        # 400 (path hors session root) ou 404 (missing) — pas de leak.
        assert r.status_code in (400, 403, 404)
