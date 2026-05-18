"""Tests for /api/models endpoints (D1)."""

from __future__ import annotations

import io
import zipfile

import pytest


class TestModelsList:
    @pytest.mark.asyncio
    async def test_no_params_returns_400(self, client):
        r = await client.get("/api/models/list")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_session_id_unknown_returns_200_empty(self, client):
        # session_id route does not validate_path; just scans the workspace
        # subdir which will not exist - returns empty list.
        r = await client.get("/api/models/list?session_id=unknown-session-id")
        assert r.status_code == 200
        assert r.json()["models"] == []

    @pytest.mark.asyncio
    async def test_arbitrary_dir_outside_workspace_returns_403(self, client, tmp_path):
        # validate_path refuses paths outside WORKSPACE_ROOT
        r = await client.get(f"/api/models/list?dir={tmp_path}")
        assert r.status_code == 403


class TestModelsUpload:
    @pytest.mark.asyncio
    async def test_non_zip_returns_400(self, client):
        r = await client.post(
            "/api/models/upload",
            files={"file": ("not.txt", b"hello", "text/plain")},
            data={"session_id": "any"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_zip_returns_400(self, client):
        r = await client.post(
            "/api/models/upload",
            files={"file": ("bad.zip", b"not a real zip", "application/zip")},
            data={"session_id": "any"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_zip_accepts_but_zero_models(self, client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("empty/.gitkeep", "")
        buf.seek(0)
        r = await client.post(
            "/api/models/upload",
            files={"file": ("models.zip", buf.read(), "application/zip")},
            data={"session_id": "sess1"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == "sess1"
        assert isinstance(data["models"], list)
