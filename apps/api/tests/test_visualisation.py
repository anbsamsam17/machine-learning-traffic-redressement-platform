"""Tests for /api/visualisation/* — upload, stream, metadata, IDOR safety."""

from __future__ import annotations

import json
import secrets

import pytest


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------


def _valid_segments_geojson() -> str:
    """Minimal segments GeoJSON: two LineString features with the required cols."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[4.83, 45.74], [4.84, 45.75]],
                },
                "properties": {
                    "agregId": "seg-001",
                    "TVr": 1500,
                    "DPL": 120,
                    "FC": 3,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [[[4.85, 45.76], [4.86, 45.77]]],
                },
                "properties": {
                    "agregId": "seg-002",
                    "TVr": 2400,
                    "DPL": 240,
                    "FC": 2,
                },
            },
        ],
    }
    return json.dumps(fc)


def _valid_segments_geojson_new_schema() -> str:
    """New 2026-05 carte schema: JOr + DPL + HPM (PM*) + HPS (PS*) + diag v3."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[4.83, 45.74], [4.84, 45.75]],
                },
                "properties": {
                    "agregId": "seg-new-001",
                    "JOr": 12500,
                    "JOrmin": 11000,
                    "JOrmax": 14000,
                    "DPL": 850,
                    "DPLmin": 700,
                    "DPLmax": 1000,
                    "PM": 1200,
                    "PMmin": 1050,
                    "PMmax": 1380,
                    "PS": 1450,
                    "PSmin": 1280,
                    "PSmax": 1620,
                    "DD": "F",
                    "HD": 90.0,
                    "alpha_eff": 0.92,
                    "alpha_source": "fcd",
                    "is_critical_zone": False,
                    "FC": 3,
                },
            },
        ],
    }
    return json.dumps(fc)


def _segments_geojson_no_line() -> str:
    """Segments GeoJSON containing only Point features — must be rejected."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [4.83, 45.74]},
                "properties": {"agregId": "p-1", "TVr": 100},
            },
        ],
    }
    return json.dumps(fc)


def _sensors_csv() -> str:
    """Minimal sensors CSV with all required columns + lat/lon."""
    return (
        "Identifiant du Poste / Section,Annee,Nom de la Commune,RD,PRD,"
        "Type de capteur,TMJA Tous Vehicules (veh/jour),TMJA Poids Lourds (veh/jour),"
        "latitude,longitude\n"
        "071.0001.03.3,2023,Lyon,RD42,12.3,Permanent,5400,320,45.7400,4.8300\n"
        "071.0002.04.1,2023,Villeurbanne,RD23,8.1,Tournant,8100,750,45.7700,4.8800\n"
        "071.0003.05.2,2023,Lyon,RD15,3.5,Permanent,0,0,45.7600,4.8500\n"
    )


def _sensors_csv_xy_aliases() -> str:
    """Sensors CSV using X / Y instead of lon / lat — alias detection."""
    return (
        "Identifiant du Poste / Section,Annee,TMJA Tous Vehicules (veh/jour),"
        "TMJA Poids Lourds (veh/jour),X,Y\n"
        "S-1,2024,1200,80,4.83,45.74\n"
    )


# ---------------------------------------------------------------------------
# Upload geojson
# ---------------------------------------------------------------------------


class TestUploadGeojson:
    @pytest.mark.asyncio
    async def test_happy_path_creates_session(self, authenticated_client, tmp_workspace):
        r = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.geojson", _valid_segments_geojson(), "application/geo+json")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"]
        assert body["filename"] == "segments.geojson"
        assert body["n_features"] == 2
        assert body["bbox"] is not None and len(body["bbox"]) == 4
        assert body["file_size_mb"] >= 0
        assert "agregId" in body["columns"]
        assert "TVr" in body["columns"]

    @pytest.mark.asyncio
    async def test_reuses_existing_session(self, authenticated_client, tmp_workspace, owned_session_id):
        r = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.geojson", _valid_segments_geojson(), "application/geo+json")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 200, r.text
        assert r.json()["session_id"] == owned_session_id

    @pytest.mark.asyncio
    async def test_rejects_geojson_without_linestring(self, authenticated_client, tmp_workspace):
        r = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("points.geojson", _segments_geojson_no_line(), "application/geo+json")},
        )
        assert r.status_code == 400
        assert "LineString" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_rejects_missing_required_cols(self, authenticated_client, tmp_workspace):
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[4.83, 45.74], [4.84, 45.75]],
                    },
                    "properties": {"foo": "bar"},  # missing agregId + TVr
                }
            ],
        }
        r = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("bad.geojson", json.dumps(fc), "application/geo+json")},
        )
        assert r.status_code == 400
        assert "agregId" in r.json()["detail"] or "TVr" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_rejects_bad_extension(self, authenticated_client, tmp_workspace):
        r = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.txt", "noop", "text/plain")},
        )
        assert r.status_code == 400
        assert ".geojson" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_accepts_new_schema_with_JOr(
        self, authenticated_client, tmp_workspace
    ):
        """Le nouveau schema carte (2026-05) expose JOr + PM/PS au lieu de TVr."""
        r = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={
                "file": (
                    "segments_new.geojson",
                    _valid_segments_geojson_new_schema(),
                    "application/geo+json",
                )
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        cols = set(body["columns"])
        # Flow nouveau schema
        assert "JOr" in cols
        assert "TVr" not in cols  # absent volontairement dans le nouveau schema
        # HPM / HPS remontes pour permettre au frontend de construire les popups
        assert {"PM", "PMmin", "PMmax"}.issubset(cols)
        assert {"PS", "PSmin", "PSmax"}.issubset(cols)
        # Diagnostic saturation v3
        assert {"alpha_eff", "alpha_source", "is_critical_zone"}.issubset(cols)
        # Direction / heading
        assert {"DD", "HD"}.issubset(cols)

    @pytest.mark.asyncio
    async def test_rejects_when_no_flow_column(
        self, authenticated_client, tmp_workspace
    ):
        """Sans JOr ni TVr -> 400 avec message mentionnant les deux colonnes."""
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[4.83, 45.74], [4.84, 45.75]],
                    },
                    "properties": {"agregId": "seg-noflow", "DPL": 100},
                }
            ],
        }
        r = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("noflow.geojson", json.dumps(fc), "application/geo+json")},
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "JOr" in detail and "TVr" in detail


# ---------------------------------------------------------------------------
# Upload sensors
# ---------------------------------------------------------------------------


class TestUploadSensors:
    @pytest.mark.asyncio
    async def test_happy_path_csv(self, authenticated_client, tmp_workspace, owned_session_id):
        r = await authenticated_client.post(
            "/api/visualisation/upload-sensors",
            files={"file": ("sensors.csv", _sensors_csv(), "text/csv")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == owned_session_id
        assert body["n_sensors"] == 3
        assert body["n_tv"] == 2  # 2 rows with TMJA TV > 0
        assert body["n_pl"] == 2
        assert body["bbox"] is not None and len(body["bbox"]) == 4

    @pytest.mark.asyncio
    async def test_xy_alias_detection(self, authenticated_client, tmp_workspace, owned_session_id):
        r = await authenticated_client.post(
            "/api/visualisation/upload-sensors",
            files={"file": ("xy.csv", _sensors_csv_xy_aliases(), "text/csv")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 200, r.text
        assert r.json()["n_sensors"] == 1

    @pytest.mark.asyncio
    async def test_rejects_without_latlon(self, authenticated_client, tmp_workspace, owned_session_id):
        csv = (
            "Identifiant du Poste / Section,TMJA Tous Vehicules (veh/jour)\n"
            "S-1,1200\n"
        )
        r = await authenticated_client.post(
            "/api/visualisation/upload-sensors",
            files={"file": ("nolatlon.csv", csv, "text/csv")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 400
        assert "lat" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET geojson / sensors / metadata
# ---------------------------------------------------------------------------


class TestStream:
    @pytest.mark.asyncio
    async def test_get_geojson_after_upload(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.geojson", _valid_segments_geojson(), "application/geo+json")},
        )
        sid = up.json()["session_id"]

        r = await authenticated_client.get(f"/api/visualisation/geojson/{sid}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/geo+json")
        body = r.json()
        assert body["type"] == "FeatureCollection"
        assert len(body["features"]) == 2

    @pytest.mark.asyncio
    async def test_get_geojson_missing_returns_404(self, authenticated_client, tmp_workspace, owned_session_id):
        r = await authenticated_client.get(f"/api/visualisation/geojson/{owned_session_id}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_get_sensors_after_upload(self, authenticated_client, tmp_workspace, owned_session_id):
        await authenticated_client.post(
            "/api/visualisation/upload-sensors",
            files={"file": ("sensors.csv", _sensors_csv(), "text/csv")},
            data={"session_id": owned_session_id},
        )
        r = await authenticated_client.get(f"/api/visualisation/sensors/{owned_session_id}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/geo+json")
        body = r.json()
        assert body["type"] == "FeatureCollection"
        assert len(body["features"]) == 3
        assert body["features"][0]["geometry"]["type"] == "Point"

    @pytest.mark.asyncio
    async def test_metadata_both(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.geojson", _valid_segments_geojson(), "application/geo+json")},
        )
        sid = up.json()["session_id"]
        await authenticated_client.post(
            "/api/visualisation/upload-sensors",
            files={"file": ("sensors.csv", _sensors_csv(), "text/csv")},
            data={"session_id": sid},
        )
        r = await authenticated_client.get(f"/api/visualisation/metadata/{sid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["segments"]["n_features"] == 2
        assert body["sensors"]["n_sensors"] == 3
        assert body["sensors"]["n_tv"] == 2

    @pytest.mark.asyncio
    async def test_metadata_segments_only(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.geojson", _valid_segments_geojson(), "application/geo+json")},
        )
        sid = up.json()["session_id"]
        r = await authenticated_client.get(f"/api/visualisation/metadata/{sid}")
        assert r.status_code == 200
        body = r.json()
        assert body["segments"] is not None
        assert body["sensors"] is None

    @pytest.mark.asyncio
    async def test_metadata_neither(self, authenticated_client, tmp_workspace, owned_session_id):
        r = await authenticated_client.get(f"/api/visualisation/metadata/{owned_session_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["segments"] is None
        assert body["sensors"] is None


# ---------------------------------------------------------------------------
# IDOR safety
# ---------------------------------------------------------------------------


class TestIDOR:
    @pytest.mark.asyncio
    async def test_user_b_cannot_access_user_a_geojson(self, client, tmp_workspace):
        # Register two users
        suffix_a = secrets.token_hex(4)
        suffix_b = secrets.token_hex(4)
        email_a = f"alice+{suffix_a}@example.com"
        email_b = f"bob+{suffix_b}@example.com"
        password = "test-password-12345"

        for email in (email_a, email_b):
            r = await client.post("/api/auth/register", json={"email": email, "password": password})
            assert r.status_code == 201

        # Login as Alice, upload a geojson
        r = await client.post("/api/auth/login", json={"email": email_a, "password": password})
        token_a = r.json()["access_token"]
        r = await client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.geojson", _valid_segments_geojson(), "application/geo+json")},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 200
        alice_sid = r.json()["session_id"]

        # Login as Bob, try to read Alice's session — must be 404 (NOT 403).
        r = await client.post("/api/auth/login", json={"email": email_b, "password": password})
        token_b = r.json()["access_token"]
        r = await client.get(
            f"/api/visualisation/geojson/{alice_sid}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404, r.text
        # Same for sensors and metadata
        r = await client.get(
            f"/api/visualisation/sensors/{alice_sid}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404
        r = await client.get(
            f"/api/visualisation/metadata/{alice_sid}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_request_blocked(self, client, tmp_workspace):
        r = await client.post(
            "/api/visualisation/upload-geojson",
            files={"file": ("segments.geojson", _valid_segments_geojson(), "application/geo+json")},
        )
        assert r.status_code == 401
