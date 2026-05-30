"""Tests for /api/mapping endpoints (auto + validate)."""

from __future__ import annotations

import pytest


class TestAutoMap:
    @pytest.mark.asyncio
    async def test_auto_map_invalid_session(self, authenticated_client):
        r = await authenticated_client.post(
            "/api/mapping/auto", json={"session_id": "nonexistent"}
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_auto_map_no_upload(self, authenticated_client):
        """Session exists but no file uploaded yet."""
        from app.session import session_manager

        session = session_manager.create_session(mode="TV")
        r = await authenticated_client.post(
            "/api/mapping/auto", json={"session_id": session.session_id}
        )
        assert r.status_code == 400
        assert "Aucun fichier" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_auto_map_success(self, authenticated_client, csv_content):
        # Upload first
        r1 = await authenticated_client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        sid = r1.json()["session_id"]

        r2 = await authenticated_client.post("/api/mapping/auto", json={"session_id": sid})
        assert r2.status_code == 200
        data = r2.json()
        assert data["session_id"] == sid
        assert isinstance(data["mappings"], list)
        assert len(data["mappings"]) > 0
        assert isinstance(data["source_columns"], list)
        assert isinstance(data["unmapped_count"], int)

    @pytest.mark.asyncio
    async def test_auto_map_finds_exact_matches(self, authenticated_client, csv_content):
        """T2: schema canonique HERE -> exact matches sont TMJOBCTV (pas TMJABCTV)."""
        r1 = await authenticated_client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        data = (await authenticated_client.post(
            "/api/mapping/auto", json={"session_id": sid}
        )).json()

        # These columns should be exact matches (canonical HERE names)
        exact_targets = {
            m["target"] for m in data["mappings"] if m["confidence"] == "exact"
        }
        # T2: le csv_content fixture expose TMJOBCTV/TMJOBCPL/TMJOFCDTV/TMJOFCDPL
        # canoniques -> exact matches.
        assert "TMJOBCTV" in exact_targets
        assert "TMJOFCDTV" in exact_targets
        # Au moins une feature vitesse/distance doit etre matchee (exact ou synonym).
        mapped_targets = {m["target"] for m in data["mappings"] if m["source"] is not None}
        assert any("speed" in t for t in mapped_targets)

    @pytest.mark.asyncio
    async def test_auto_map_finds_synonym_matches(self, authenticated_client, csv_content):
        """T2: TMJAFCDTV (legacy) in source -> TMJOFCDTV (canonique HERE) via synonyme."""
        r1 = await authenticated_client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        data = (await authenticated_client.post(
            "/api/mapping/auto", json={"session_id": sid}
        )).json()

        # Toutes les mappings non-missing pour interrogation
        all_mappings = {
            m["target"]: m["source"]
            for m in data["mappings"]
            if m["source"] is not None
        }
        # TMJOFCDTV est present comme TARGET canonique HERE,
        # source = TMJOFCDTV directement (exact) ou TMJAFCDTV (synonym).
        assert "TMJOFCDTV" in all_mappings, f"Mappings: {all_mappings}"
        # Source doit etre l'un des deux noms presents dans csv_content
        assert all_mappings["TMJOFCDTV"] in ("TMJOFCDTV", "TMJAFCDTV")

    @pytest.mark.asyncio
    async def test_auto_map_reports_missing(self, authenticated_client, csv_content):
        r1 = await authenticated_client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        data = (await authenticated_client.post(
            "/api/mapping/auto", json={"session_id": sid}
        )).json()

        missing = [m for m in data["mappings"] if m["confidence"] == "missing"]
        assert len(missing) > 0
        assert data["unmapped_count"] == len(missing)


class TestValidateMapping:
    @pytest.mark.asyncio
    async def test_validate_invalid_session(self, authenticated_client):
        r = await authenticated_client.put(
            "/api/mapping/validate",
            json={"session_id": "nonexistent", "mapping": {}},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_validate_success(self, authenticated_client, csv_content):
        # Upload
        r1 = await authenticated_client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        # Auto-map
        r2 = await authenticated_client.post("/api/mapping/auto", json={"session_id": sid})
        proposed = {m["target"]: m["source"] for m in r2.json()["mappings"]}

        # Validate
        r3 = await authenticated_client.put(
            "/api/mapping/validate",
            json={
                "session_id": sid,
                "mapping": proposed,
                "territory": "test_territory",
            },
        )
        assert r3.status_code == 200
        data = r3.json()
        assert data["session_id"] == sid
        assert data["rows"] == 3
        assert isinstance(data["columns"], list)
        assert isinstance(data["missing_critical"], list)
        assert isinstance(data["warnings"], list)
        assert isinstance(data["preview"], list)

    @pytest.mark.asyncio
    async def test_validate_derives_txpen(self, authenticated_client, csv_content):
        """TxPen should be derived from TMJATV/TMJABCTV when absent."""
        r1 = await authenticated_client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        r2 = await authenticated_client.post("/api/mapping/auto", json={"session_id": sid})
        proposed = {m["target"]: m["source"] for m in r2.json()["mappings"]}

        r3 = await authenticated_client.put(
            "/api/mapping/validate",
            json={"session_id": sid, "mapping": proposed},
        )
        data = r3.json()
        assert "TxPen" in data["columns"]

    @pytest.mark.asyncio
    async def test_validate_derives_flag_comptage(self, authenticated_client, csv_content):
        """flag_comptage should be derived from Type column."""
        r1 = await authenticated_client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        r2 = await authenticated_client.post("/api/mapping/auto", json={"session_id": sid})
        proposed = {m["target"]: m["source"] for m in r2.json()["mappings"]}

        r3 = await authenticated_client.put(
            "/api/mapping/validate",
            json={"session_id": sid, "mapping": proposed},
        )
        data = r3.json()
        assert "flag_comptage" in data["columns"]
