"""Tests for /api/models endpoints (D1).

Updated for P0-3 / P0-4 (audit 02): every endpoint that takes a ``session_id``
now requires the caller to own the session, and the ``root``/``dir`` query
param must stay inside the caller's per-session tree.
"""

from __future__ import annotations

import io
import zipfile

import pytest


class TestModelsList:
    @pytest.mark.asyncio
    async def test_no_params_returns_400(self, authenticated_client):
        r = await authenticated_client.get("/api/models/list")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_session_id_unknown_returns_404(self, authenticated_client):
        # P0-3: unknown / unowned sessions are refused with 404 (same response
        # as a non-existent session so callers cannot enumerate ids).
        r = await authenticated_client.get("/api/models/list?session_id=unknown-session-id")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_arbitrary_dir_without_session_id_returns_400(
        self, authenticated_client, tmp_path
    ):
        # P0-4: `root` / `dir` is meaningless without a session_id to scope it
        # against; the endpoint refuses cross-tenant exploration with 400.
        r = await authenticated_client.get(f"/api/models/list?dir={tmp_path}")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_arbitrary_dir_outside_session_returns_403(
        self, authenticated_client, owned_session_id, tmp_path
    ):
        # P0-4: even with a valid owned session_id, paths outside the
        # caller's per-session tree are refused with 403.
        r = await authenticated_client.get(
            f"/api/models/list?dir={tmp_path}&session_id={owned_session_id}"
        )
        assert r.status_code == 403


class TestModelsUpload:
    @pytest.mark.asyncio
    async def test_non_zip_returns_400(self, authenticated_client, owned_session_id):
        r = await authenticated_client.post(
            "/api/models/upload",
            files={"file": ("not.txt", b"hello", "text/plain")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_zip_returns_400(self, authenticated_client, owned_session_id):
        r = await authenticated_client.post(
            "/api/models/upload",
            files={"file": ("bad.zip", b"not a real zip", "application/zip")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_zip_accepts_but_zero_models(self, authenticated_client, owned_session_id):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("empty/.gitkeep", "")
        buf.seek(0)
        r = await authenticated_client.post(
            "/api/models/upload",
            files={"file": ("models.zip", buf.read(), "application/zip")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["session_id"] == owned_session_id
        assert isinstance(data["models"], list)

    @pytest.mark.asyncio
    async def test_upload_to_unowned_session_returns_404(self, authenticated_client):
        # P0-3: refuse upload to a session the caller does not own.
        r = await authenticated_client.post(
            "/api/models/upload",
            files={"file": ("models.zip", b"x", "application/zip")},
            data={"session_id": "not-my-session"},
        )
        assert r.status_code == 404
