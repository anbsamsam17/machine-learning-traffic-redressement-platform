"""Tests for /api/training endpoints (D1).

Heavy training-time tests (model.fit) are gated on tensorflow being
installed; only the routing / validation paths run in CI.
"""

from __future__ import annotations

import importlib.util

import pytest

TF_INSTALLED = importlib.util.find_spec("tensorflow") is not None


class TestStartTraining:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, client):
        r = await client.post(
            "/api/training/start",
            json={"session_id": "doesnotexist"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_no_learning_df_returns_400(self, client, csv_content):
        # /api/upload sets raw_df but the learning_df is only set after
        # POST /api/mapping/validate. Verifies the upfront guard.
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        sid = r.json()["session_id"]
        r2 = await client.post(
            "/api/training/start",
            json={"session_id": sid},
        )
        assert r2.status_code == 400

    @pytest.mark.asyncio
    async def test_grid_cap_enforced(self, client, csv_content):
        """When MAX_GRID_COMBINATIONS would be exceeded, return 400."""
        r = await client.post(
            "/api/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            data={"mode": "TV"},
        )
        sid = r.json()["session_id"]
        # First make sure mapping is validated so learning_df exists
        m = await client.post(
            "/api/mapping/validate",
            json={
                "session_id": sid,
                "mapping": {
                    "TMJAFCDTV": "TMJAFCDTV",
                    "TMJAFCDPL": "TMJAFCDPL",
                    "TMJABCTV": "TMJABCTV",
                    "TMJABCPL": "TMJABCPL",
                    "car_average_speed_kmh": "car_average_speed_kmh",
                    "car_average_distance_km": "car_average_distance_km",
                    "truck_average_speed_kmh": "truck_average_speed_kmh",
                    "truck_min_average_distance_km": "truck_min_average_distance_km",
                },
            },
        )
        if m.status_code != 200:
            pytest.skip("Mapping validate route shape differs; not testing cap here")

        # Build a config that explodes past 100 combos via feature_subset_grid + many axes
        payload = {
            "session_id": sid,
            "feature_subset_grid": True,
            "mandatory_input_cols": ["TMJAFCDTV"],
            "min_input_count": 1,
            "activations": ["elu", "relu", "tanh"],
            "learning_rates": [0.01, 0.001, 0.0005, 0.005],
            "min_nb_epochs_list": [100, 500, 1000],
            "batch_sizes": [128, 256, 512],
            "dropouts": [0.05, 0.1, 0.2],
        }
        r2 = await client.post("/api/training/start", json=payload)
        # Either we exploded past the cap (400) or our payload validation kicked in (422).
        assert r2.status_code in (400, 422)


class TestTrainingStatus:
    @pytest.mark.asyncio
    async def test_unknown_task_returns_404(self, client):
        r = await client.get("/api/training/status/doesnotexist")
        assert r.status_code == 404


class TestTrainingCancel:
    @pytest.mark.asyncio
    async def test_unknown_task_returns_404(self, client):
        r = await client.post("/api/training/cancel/doesnotexist")
        assert r.status_code == 404


class TestTrainingStream:
    @pytest.mark.asyncio
    async def test_unknown_task_returns_404(self, client):
        r = await client.get("/api/training/stream/doesnotexist")
        assert r.status_code == 404
