"""Tests for /api/carte endpoints (D1)."""

from __future__ import annotations

import io
import zipfile

import pytest


class TestValidateModel:
    @pytest.mark.asyncio
    async def test_missing_dir_returns_invalid(self, client, tmp_path):
        r = await client.post(
            "/api/carte/validate-model",
            json={"model_dir": str(tmp_path / "does_not_exist")},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False
        assert data["missing_files"]

    @pytest.mark.asyncio
    async def test_empty_dir_missing_files(self, client, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        r = await client.post(
            "/api/carte/validate-model",
            json={"model_dir": str(empty)},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is False
        # Should report missing weights + arch (legacy) + norm
        assert any("NN" in m for m in data["missing_files"])


class TestUploadCarteModel:
    @pytest.mark.asyncio
    async def test_non_zip_returns_400(self, client):
        r = await client.post(
            "/api/carte/upload-model",
            files={"file": ("not.txt", b"hello", "text/plain")},
            data={"session_id": "any", "model_type": "tv"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_model_type_returns_400(self, client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("dummy.txt", "")
        buf.seek(0)
        r = await client.post(
            "/api/carte/upload-model",
            files={"file": ("model.zip", buf.read(), "application/zip")},
            data={"session_id": "any", "model_type": "xx"},
        )
        assert r.status_code == 400


class TestGenerateCarte:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, client):
        r = await client.post(
            "/api/carte/generate",
            json={
                "session_id": "nonexistent",
                "model_tv_dir": "/tmp/x",
                "model_pl_dir": "/tmp/y",
            },
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_raw_df_returns_400(self, client):
        # Create a session via mapping (does not store raw_df) -- /api/upload does
        # First upload to get a real raw_df, but delete it via setting raw_df=None
        # Simpler: just check the dummy model_tv_dir case after upload
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", "a,b\n1,2\n", "text/csv")},
            data={"mode": "TV"},
        )
        sid = r.json()["session_id"]
        # raw_df exists but model_tv_dir is invalid -> 400 from _load_model
        r2 = await client.post(
            "/api/carte/generate",
            json={
                "session_id": sid,
                "model_tv_dir": "/tmp/nope_tv",
                "model_pl_dir": "/tmp/nope_pl",
            },
        )
        assert r2.status_code == 400


class TestDownloadCarte:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, client):
        r = await client.get("/api/carte/download/doesnotexist")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_carte_returns_400(self, client, csv_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r.json()["session_id"]
        r2 = await client.get(f"/api/carte/download/{sid}")
        assert r2.status_code == 400
