"""Tests for /api/mapping endpoints (auto + validate)."""

from __future__ import annotations

import pytest


class TestAutoMap:
    @pytest.mark.asyncio
    async def test_auto_map_invalid_session(self, client):
        r = await client.post(
            "/api/mapping/auto", json={"session_id": "nonexistent"}
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_auto_map_no_upload(self, client):
        """Session exists but no file uploaded yet."""
        from app.session import session_manager

        session = session_manager.create_session(mode="TV")
        r = await client.post(
            "/api/mapping/auto", json={"session_id": session.session_id}
        )
        assert r.status_code == 400
        assert "Aucun fichier" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_auto_map_success(self, client, csv_content):
        # Upload first
        r1 = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        sid = r1.json()["session_id"]

        r2 = await client.post("/api/mapping/auto", json={"session_id": sid})
        assert r2.status_code == 200
        data = r2.json()
        assert data["session_id"] == sid
        assert isinstance(data["mappings"], list)
        assert len(data["mappings"]) > 0
        assert isinstance(data["source_columns"], list)
        assert isinstance(data["unmapped_count"], int)

    @pytest.mark.asyncio
    async def test_auto_map_finds_exact_matches(self, client, csv_content):
        r1 = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        data = (await client.post(
            "/api/mapping/auto", json={"session_id": sid}
        )).json()

        # These columns should be exact matches
        exact_targets = {
            m["target"] for m in data["mappings"] if m["confidence"] == "exact"
        }
        assert "Type" in exact_targets
        assert "TMJABCTV" in exact_targets
        assert "car_average_speed_kmh" in exact_targets

    @pytest.mark.asyncio
    async def test_auto_map_finds_synonym_matches(self, client, csv_content):
        """TMJAFCDTV in source -> TMJATV target via synonym."""
        r1 = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        data = (await client.post(
            "/api/mapping/auto", json={"session_id": sid}
        )).json()

        synonym_mappings = {
            m["target"]: m["source"]
            for m in data["mappings"]
            if m["confidence"] == "synonym"
        }
        # TMJAFCDTV is a synonym for target "TMJATV"
        assert "TMJATV" in synonym_mappings
        assert synonym_mappings["TMJATV"] == "TMJAFCDTV"

    @pytest.mark.asyncio
    async def test_auto_map_reports_missing(self, client, csv_content):
        r1 = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        data = (await client.post(
            "/api/mapping/auto", json={"session_id": sid}
        )).json()

        missing = [m for m in data["mappings"] if m["confidence"] == "missing"]
        assert len(missing) > 0
        assert data["unmapped_count"] == len(missing)


class TestValidateMapping:
    @pytest.mark.asyncio
    async def test_validate_invalid_session(self, client):
        r = await client.put(
            "/api/mapping/validate",
            json={"session_id": "nonexistent", "mapping": {}},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_validate_success(self, client, csv_content):
        # Upload
        r1 = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        # Auto-map
        r2 = await client.post("/api/mapping/auto", json={"session_id": sid})
        proposed = {m["target"]: m["source"] for m in r2.json()["mappings"]}

        # Validate
        r3 = await client.put(
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
    async def test_validate_derives_txpen(self, client, csv_content):
        """TxPen should be derived from TMJATV/TMJABCTV when absent."""
        r1 = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        r2 = await client.post("/api/mapping/auto", json={"session_id": sid})
        proposed = {m["target"]: m["source"] for m in r2.json()["mappings"]}

        r3 = await client.put(
            "/api/mapping/validate",
            json={"session_id": sid, "mapping": proposed},
        )
        data = r3.json()
        assert "TxPen" in data["columns"]

    @pytest.mark.asyncio
    async def test_validate_derives_flag_comptage(self, client, csv_content):
        """flag_comptage should be derived from Type column."""
        r1 = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        r2 = await client.post("/api/mapping/auto", json={"session_id": sid})
        proposed = {m["target"]: m["source"] for m in r2.json()["mappings"]}

        r3 = await client.put(
            "/api/mapping/validate",
            json={"session_id": sid, "mapping": proposed},
        )
        data = r3.json()
        assert "flag_comptage" in data["columns"]
