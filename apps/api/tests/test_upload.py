"""Tests for POST /api/upload endpoints."""

from __future__ import annotations

import json
import io

import pytest


class TestUploadCSV:
    @pytest.mark.asyncio
    async def test_upload_csv_returns_200(self, client, csv_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_csv_response_shape(self, client, csv_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        data = r.json()
        assert "session_id" in data
        assert data["filename"] == "test.csv"
        assert data["rows"] == 3
        assert isinstance(data["columns"], list)
        assert len(data["columns"]) == 10
        assert isinstance(data["preview"], list)
        assert len(data["preview"]) == 3

    @pytest.mark.asyncio
    async def test_upload_csv_columns_present(self, client, csv_content):
        data = (await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )).json()
        assert "TMJAFCDTV" in data["columns"]
        assert "car_average_speed_kmh" in data["columns"]

    @pytest.mark.asyncio
    async def test_upload_csv_default_mode(self, client, csv_content):
        """Mode defaults to TV when not specified."""
        r = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_csv_pl_mode(self, client, csv_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("test.csv", csv_content, "text/csv")},
            data={"mode": "PL"},
        )
        assert r.status_code == 200


class TestUploadGeoJSON:
    @pytest.mark.asyncio
    async def test_upload_geojson_returns_200(self, client, geojson_content):
        r = await client.post(
            "/api/upload",
            files={"file": ("test.geojson", geojson_content, "application/json")},
            data={"mode": "TV"},
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_geojson_has_geometry_cols(self, client, geojson_content):
        data = (await client.post(
            "/api/upload",
            files={"file": ("test.geojson", geojson_content, "application/json")},
            data={"mode": "TV"},
        )).json()
        assert data["rows"] == 2
        # GeoJSON parser adds __lat, __lon, geometry, __geometry_json
        assert "__lat" in data["columns"]
        assert "__lon" in data["columns"]

    @pytest.mark.asyncio
    async def test_upload_geojson_preview_serializable(self, client, geojson_content):
        """Geometry dicts in preview should be JSON-serialized to strings."""
        data = (await client.post(
            "/api/upload",
            files={"file": ("test.geojson", geojson_content, "application/json")},
            data={"mode": "TV"},
        )).json()
        for row in data["preview"]:
            for v in row.values():
                # No raw dict values -- they should be strings or numbers
                assert not isinstance(v, dict)


class TestUploadValidation:
    @pytest.mark.asyncio
    async def test_upload_no_file_returns_422(self, client):
        r = await client.post("/api/upload")
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_unsupported_format_returns_400(self, client):
        r = await client.post(
            "/api/upload",
            files={"file": ("test.xyz", b"some data", "application/octet-stream")},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_invalid_csv_encoding(self, client):
        # Valid CSV but with unusual bytes -- should still try to decode
        content = b"col1,col2\n\xff\xfe,value"
        r = await client.post(
            "/api/upload",
            files={"file": ("test.csv", content, "text/csv")},
        )
        # Should succeed with latin-1 or cp1252 fallback
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_upload_bad_json_returns_400(self, client):
        r = await client.post(
            "/api/upload",
            files={"file": ("test.geojson", b"not valid json", "application/json")},
        )
        assert r.status_code == 400


class TestUploadValidationData:
    @pytest.mark.asyncio
    async def test_validation_upload_invalid_session(self, client, csv_content):
        r = await client.post(
            "/api/upload/validation",
            files={"file": ("val.csv", csv_content, "text/csv")},
            data={"session_id": "nonexistent"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_validation_upload_success(self, client, csv_content):
        # Create session via upload
        r1 = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        sid = r1.json()["session_id"]

        r2 = await client.post(
            "/api/upload/validation",
            files={"file": ("val.csv", csv_content, "text/csv")},
            data={"session_id": sid},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["session_id"] == sid
        assert data["rows"] == 3
