"""Shared pytest fixtures and configuration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure the app package is importable
api_root = Path(__file__).resolve().parent.parent
if str(api_root) not in sys.path:
    sys.path.insert(0, str(api_root))

from app.main import app
from app.session import session_manager


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Async test client backed by the FastAPI app (no real server needed)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def csv_content() -> str:
    """Minimal valid CSV with columns needed for mapping + training."""
    return (
        "Type,Identifiant,TMJAFCDTV,TMJAFCDPL,TMJABCTV,TMJABCPL,"
        "car_average_speed_kmh,car_average_distance_km,"
        "truck_average_speed_kmh,truck_min_average_distance_km\n"
        "Per,001,100,10,5000,500,60,30,55,3\n"
        "Tou,002,200,20,8000,800,65,35,58,4\n"
        "Per,003,150,15,6000,600,62,32,56,3.5\n"
    )


@pytest.fixture
def geojson_content() -> str:
    """Minimal valid GeoJSON FeatureCollection."""
    return json.dumps({
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2.35, 48.86]},
                "properties": {
                    "Type": "Per",
                    "Identifiant": "001",
                    "TMJAFCDTV": 100,
                    "TMJAFCDPL": 10,
                    "TMJABCTV": 5000,
                    "TMJABCPL": 500,
                    "car_average_speed_kmh": 60,
                    "car_average_distance_km": 30,
                    "truck_average_speed_kmh": 55,
                    "truck_min_average_distance_km": 3,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [2.36, 48.87]},
                "properties": {
                    "Type": "Tou",
                    "Identifiant": "002",
                    "TMJAFCDTV": 200,
                    "TMJAFCDPL": 20,
                    "TMJABCTV": 8000,
                    "TMJABCPL": 800,
                    "car_average_speed_kmh": 65,
                    "car_average_distance_km": 35,
                    "truck_average_speed_kmh": 58,
                    "truck_min_average_distance_km": 4,
                },
            },
        ],
    })


@pytest.fixture(autouse=True)
def _cleanup_sessions():
    """Ensure sessions are cleaned up between tests."""
    yield
    with session_manager._lock:
        session_manager._sessions.clear()
