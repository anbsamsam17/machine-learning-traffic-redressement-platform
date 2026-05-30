"""Tests pour /api/discontinuites/* — upload + analyze + nodes + stats + IDOR.

Synthetic geojson : un mini reseau de 10 aretes oriente avec :
  - quelques noeuds clairement discontinus (ecart > 4000 v/j sur axe principal) ;
  - un noeud "Continuite" (1 in + 1 out, sans RAMP/RB) qui doit tomber dans
    la classe Continuite et declencher FCD_TV_cliff ;
  - quelques noeuds frontaliers exclus par la regle utilisateur.
"""

from __future__ import annotations

import io
import json
import secrets

import pytest


# ---------------------------------------------------------------------------
# Sample synthetic geojson — 10 segments, 3 chaines + bretelles + rond-point
# ---------------------------------------------------------------------------


def _make_segment(
    agreg_id: str,
    ref: int,
    nref: int,
    tvr: float,
    coords: list[list[float]],
    *,
    tmjo_tv: float = 5000.0,
    tmjo_pl: float = 500.0,
    fc: int = 3,
    ramp: str = "N",
    roundabout: str = "N",
    func_class: int | None = None,
) -> dict:
    """Helper pour construire une feature LineString conforme au schema HERE."""
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "agregId": agreg_id,
            "REF_IN_ID": ref,
            "NREF_IN_ID": nref,
            "TVr": tvr,
            "TMJOFCDTV": tmjo_tv,
            "TMJOFCDPL": tmjo_pl,
            "FC": fc,
            "functional_class": func_class if func_class is not None else fc,
            "RAMP": ramp,
            "ROUNDABOUT": roundabout,
        },
    }


def _synthetic_network() -> dict:
    """Reseau synthetique pour les tests.

    Layout (id_noeud -> chaine) :

      Chaine principale :  1 --[A-F (TVr=15000)]--> 2 --[B-F (TVr=4500)]--> 3
      (cliff TVr a noeud 2 : in=15000, out=4500, ecart=10500 >> 4000 sur axe >20k => RED)

      Une 2eme branche entre au noeud 2 :  4 --[C-F (TVr=8000)]--> 2
      Ce noeud 2 devient un carrefour 2 in / 1 out.

      Continuite suspecte :  10 --[D-F (TVr=12000)]--> 11 --[E-F (TVr=3000)]--> 12
      (noeud 11 : 1 in + 1 out, ecart 9000 v/j >> 4000 si max>20k... ici max=12000<=20k => seuil 2000)
      ecart=9000 > seuil 2000 => RED, topology=Continuite

      Bretelle :  20 --[F-F RAMP=Y TVr=2000]--> 21 --[G-F TVr=8000]--> 22
      noeud 21 : ecart=6000 v/j, max=8000 => seuil 2000 (max<=20k) => RED, topology=Bretelle

      Frontalier :  30 --[H-F TVr=10000]--> 31  (noeud 31 n'a aucun out => boundary, exclu)
                    32 --[I-F TVr=10000]--> 33  (idem)
                    34 --[J-F TVr=5000]--> 35  (idem)
    """
    features = [
        # Chaine 1 + 2 (noeud 2 = carrefour avec cliff FCD)
        _make_segment(
            "A-F", 1, 2, tvr=15000,
            coords=[[4.83, 45.74], [4.84, 45.75]],
            tmjo_tv=12000, tmjo_pl=800, fc=2,
        ),
        _make_segment(
            "B-F", 2, 3, tvr=4500,
            coords=[[4.84, 45.75], [4.85, 45.76]],
            tmjo_tv=3000, tmjo_pl=200, fc=3,
        ),
        _make_segment(
            "C-F", 4, 2, tvr=8000,
            coords=[[4.83, 45.76], [4.84, 45.75]],
            tmjo_tv=200, tmjo_pl=50, fc=3,   # tres faible vs A (cliff TV)
        ),
        # Continuite suspecte (noeud 11 = 1 in + 1 out, sans RAMP/RB)
        _make_segment(
            "D-F", 10, 11, tvr=12000,
            coords=[[4.86, 45.74], [4.87, 45.75]],
            tmjo_tv=8000, tmjo_pl=600, fc=3,
        ),
        _make_segment(
            "E-F", 11, 12, tvr=3000,
            coords=[[4.87, 45.75], [4.88, 45.76]],
            tmjo_tv=1500, tmjo_pl=100, fc=3,
        ),
        # Bretelle (noeud 21 = 1 in (RAMP) + 1 out)
        _make_segment(
            "F-F", 20, 21, tvr=2000,
            coords=[[4.89, 45.74], [4.90, 45.75]],
            tmjo_tv=1000, tmjo_pl=80, fc=4, ramp="Y",
        ),
        _make_segment(
            "G-F", 21, 22, tvr=8000,
            coords=[[4.90, 45.75], [4.91, 45.76]],
            tmjo_tv=5000, tmjo_pl=400, fc=3,
        ),
        # Frontaliers (3 paires de in/out non equilibres)
        _make_segment(
            "H-F", 30, 31, tvr=10000,
            coords=[[4.92, 45.74], [4.93, 45.75]],
        ),
        _make_segment(
            "I-F", 32, 33, tvr=10000,
            coords=[[4.94, 45.74], [4.95, 45.75]],
        ),
        _make_segment(
            "J-F", 34, 35, tvr=5000,
            coords=[[4.96, 45.74], [4.97, 45.75]],
        ),
    ]
    return {"type": "FeatureCollection", "features": features}


def _synthetic_geojson_str() -> str:
    return json.dumps(_synthetic_network())


def _light_network() -> dict:
    """Variante "light" du reseau : TVr / REF / NREF / RAMP / ROUNDABOUT / FC,
    mais sans aucune colonne FCD (TMJOFCDTV, TMJOFCDPL, ...).

    Reproduit la situation `2025_light.geojson` decrit par l'expert trafic :
    sans inputs FCD, le pipeline doit retomber en mode degrade (Coverage_gap
    dominant) sauf si un parquet FCDREFGLOBAL est joint.
    """
    fc = _synthetic_network()
    fcd_cols_to_drop = (
        "TMJOFCDTV",
        "TMJOFCDPL",
        "functional_class",
        "avg_distance_before_m",
        "avg_min_distance_m",
        "truck_avg_distance_before_m",
    )
    for feat in fc["features"]:
        for col in fcd_cols_to_drop:
            feat["properties"].pop(col, None)
    return fc


def _build_fcd_parquet_bytes(network: dict) -> bytes:
    """Construit un parquet FCDREFGLOBAL synthetique aligne sur le reseau.

    Le parquet emule la sortie reelle : 1 ligne par segment_id, colonnes FCD
    completes (TMJOFCDTV/PL realistes + functional_class + RAMP/ROUNDABOUT +
    distances). Le mapping est volontairement aligne sur le `_synthetic_network`
    pour qu'au moins un noeud declenche FCD_TV_cliff apres jointure.
    """
    import pandas as pd

    rows: list[dict] = []
    for feat in network["features"]:
        props = feat["properties"]
        rows.append({
            "segment_id": str(props["agregId"]),
            "TMJOFCDTV": float(props.get("TMJOFCDTV", 5000.0)),
            "TMJOFCDPL": float(props.get("TMJOFCDPL", 500.0)),
            "functional_class": int(props.get("functional_class", props.get("FC", 3))),
            "RAMP": str(props.get("RAMP", "N")),
            "ROUNDABOUT": str(props.get("ROUNDABOUT", "N")),
            "avg_distance_before_m": 120.0,
            "avg_min_distance_m": 80.0,
            "truck_avg_distance_before_m": 130.0,
        })
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_parquet(buf, engine="pyarrow", compression="snappy")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests upload
# ---------------------------------------------------------------------------


class TestUploadGeojson:
    @pytest.mark.asyncio
    async def test_happy_path_creates_session(self, authenticated_client, tmp_workspace):
        r = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"]
        assert body["n_features"] == 10
        assert body["bbox"] is not None and len(body["bbox"]) == 4
        assert "agregId" in body["columns"]
        assert "TVr" in body["columns"]
        assert "REF_IN_ID" in body["columns"]

    @pytest.mark.asyncio
    async def test_warns_without_graph_columns(self, authenticated_client, tmp_workspace):
        """REF_IN_ID/NREF_IN_ID absents : upload accepte avec un warning,
        car ces colonnes peuvent etre fournies via /upload-fcd ulterieurement.
        """
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[4.83, 45.74], [4.84, 45.75]],
                    },
                    "properties": {"agregId": "seg-1", "TVr": 100},  # REF/NREF absents
                }
            ],
        }
        r = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("noref.geojson", json.dumps(fc), "application/geo+json")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["graph_columns_present"] is False
        assert body["warning"] is not None
        assert "REF_IN_ID" in body["warning"]

    @pytest.mark.asyncio
    async def test_rejects_no_linestring(self, authenticated_client, tmp_workspace):
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [4.83, 45.74]},
                    "properties": {"agregId": "p-1", "TVr": 100, "REF_IN_ID": 1, "NREF_IN_ID": 2},
                }
            ],
        }
        r = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("points.geojson", json.dumps(fc), "application/geo+json")},
        )
        assert r.status_code == 400
        assert "LineString" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Tests analyze
# ---------------------------------------------------------------------------


class TestAnalyze:
    @pytest.mark.asyncio
    async def test_full_pipeline_flags_expected_nodes(self, authenticated_client, tmp_workspace):
        # Upload
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        assert up.status_code == 200
        sid = up.json()["session_id"]

        # Analyze
        r = await authenticated_client.post(
            "/api/discontinuites/analyze",
            data={"session_id": sid},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == sid
        # 3 noeuds flagues attendus: 2 (carrefour TV cliff), 11 (continuite), 21 (bretelle)
        assert body["n_nodes_flagged"] >= 3
        assert body["n_edges"] == 10
        # Au moins 1 noeud rouge (ecart >= 2x seuil) attendu
        assert sum(body["n_tier"].values()) == body["n_nodes_flagged"]
        # Au moins une cause FCD_TV_cliff dans la chaine A/C
        assert body["n_causes"].get("FCD_TV_cliff", 0) >= 1
        # Au moins une topologie Continuite attendue (noeud 11)
        assert body["n_topology"].get("Continuite", 0) >= 1
        # Frontaliers (noeuds 30/31/32/33/34/35 + 1/3 etc.) exclus
        assert body["n_boundary_nodes"] >= 6
        assert body["pipeline_duration_s"] >= 0

    @pytest.mark.asyncio
    async def test_analyze_without_upload_returns_404(self, authenticated_client, tmp_workspace, owned_session_id):
        r = await authenticated_client.post(
            "/api/discontinuites/analyze",
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests GET nodes + stats
# ---------------------------------------------------------------------------


class TestStream:
    @pytest.mark.asyncio
    async def test_get_nodes_after_analyze(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        sid = up.json()["session_id"]
        an = await authenticated_client.post(
            "/api/discontinuites/analyze", data={"session_id": sid}
        )
        assert an.status_code == 200

        r = await authenticated_client.get(f"/api/discontinuites/nodes/{sid}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/geo+json")
        body = r.json()
        assert body["type"] == "FeatureCollection"
        assert "metadata" in body
        assert body["metadata"]["version"] == "v3"
        # Toutes les features doivent avoir un Point + les champs requis
        for feat in body["features"]:
            assert feat["geometry"]["type"] == "Point"
            p = feat["properties"]
            for key in ("node_id", "ecart", "flow_in", "flow_out", "principal_cause",
                        "topology", "tier", "narrative", "drivers", "driver_scores",
                        "edges_in", "edges_out"):
                assert key in p, f"propriete absente: {key}"

    @pytest.mark.asyncio
    async def test_get_nodes_before_analyze_returns_404(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        sid = up.json()["session_id"]
        r = await authenticated_client.get(f"/api/discontinuites/nodes/{sid}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_stats_endpoint_returns_cross_tab(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        sid = up.json()["session_id"]
        await authenticated_client.post("/api/discontinuites/analyze", data={"session_id": sid})

        r = await authenticated_client.get(f"/api/discontinuites/stats/{sid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == sid
        assert body["n_features"] >= 3
        assert body["n_edges"] == 10
        assert "cross_tab" in body
        # Le cross-tab doit refleter au moins 1 categorie
        total_in_cross = sum(
            sum(topos.values()) for topos in body["cross_tab"].values()
        )
        assert total_in_cross == body["n_features"]
        # Seuils user rule exposes
        assert body["user_rule"]["low_threshold"] == 2000.0
        assert body["user_rule"]["high_threshold"] == 4000.0
        assert body["user_rule"]["pivot"] == 20000.0


# ---------------------------------------------------------------------------
# Tests IDOR
# ---------------------------------------------------------------------------


class TestIDOR:
    @pytest.mark.asyncio
    async def test_user_b_cannot_access_user_a_results(self, client, tmp_workspace):
        suffix_a = secrets.token_hex(4)
        suffix_b = secrets.token_hex(4)
        email_a = f"alice+{suffix_a}@example.com"
        email_b = f"bob+{suffix_b}@example.com"
        password = "test-password-12345"

        for email in (email_a, email_b):
            r = await client.post("/api/auth/register", json={"email": email, "password": password})
            assert r.status_code == 201

        r = await client.post("/api/auth/login", json={"email": email_a, "password": password})
        token_a = r.json()["access_token"]
        up = await client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert up.status_code == 200
        alice_sid = up.json()["session_id"]
        # Lance le pipeline cote Alice
        an = await client.post(
            "/api/discontinuites/analyze",
            data={"session_id": alice_sid},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert an.status_code == 200

        # Bob essaie d'acceder a la session d'Alice
        r = await client.post("/api/auth/login", json={"email": email_b, "password": password})
        token_b = r.json()["access_token"]
        bob_hdr = {"Authorization": f"Bearer {token_b}"}

        r = await client.get(f"/api/discontinuites/nodes/{alice_sid}", headers=bob_hdr)
        assert r.status_code == 404, r.text

        r = await client.get(f"/api/discontinuites/stats/{alice_sid}", headers=bob_hdr)
        assert r.status_code == 404, r.text

        r = await client.post(
            "/api/discontinuites/analyze",
            data={"session_id": alice_sid},
            headers=bob_hdr,
        )
        assert r.status_code == 404, r.text

    @pytest.mark.asyncio
    async def test_unauthenticated_blocked(self, client, tmp_workspace):
        r = await client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Validation directe du service (smoke test sans HTTP)
# ---------------------------------------------------------------------------


class TestServiceDirect:
    """Petit test direct du service pour valider la logique sans HTTP."""

    def test_service_pipeline_on_synthetic_network(self):
        # Import retarde pour eviter de charger geopandas en collecte parallele.
        import geopandas as gpd

        from app.services import discontinuites as svc

        fc = _synthetic_network()
        gdf = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
        out_fc, stats = svc.run_full_pipeline(gdf)

        assert out_fc["type"] == "FeatureCollection"
        assert isinstance(stats["pipeline_duration_s"], float)
        assert stats["n_features"] == len(out_fc["features"])
        # Au moins un noeud flagué attendu (>= 3)
        assert stats["n_features"] >= 3
        # FCD_TV_cliff doit ressortir dans le cross-tab
        assert "FCD_TV_cliff" in stats["n_causes"]
        # Sans parquet FCD fourni, le pipeline n'a pas joint.
        assert stats["fcd_joined"] is False
        assert stats["fcd_columns_count"] == 0

    def test_service_pipeline_join_fcd_restores_cliffs(self):
        """Sur un reseau light (sans FCD), la jointure parquet restaure FCD_*_cliff."""
        import geopandas as gpd
        import pandas as pd

        from app.services import discontinuites as svc

        # Reseau light : pas d'inputs FCD du tout dans le geojson.
        fc = _light_network()
        gdf = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")

        # 1) Mode degrade : sans jointure, on perd FCD_TV_cliff.
        _, stats_degraded = svc.run_full_pipeline(gdf)
        assert stats_degraded["fcd_joined"] is False
        # Sans inputs FCD, FCD_TV_cliff ne peut pas se declencher.
        assert stats_degraded["n_causes"].get("FCD_TV_cliff", 0) == 0
        # En revanche, Coverage_gap explose (mode degrade attendu).
        n_total = sum(stats_degraded["n_causes"].values())
        if n_total > 0:
            assert stats_degraded["n_causes"].get("Coverage_gap", 0) > 0

        # 2) Avec jointure : on doit retrouver au moins un FCD_TV_cliff.
        fcd_bytes = _build_fcd_parquet_bytes(_synthetic_network())
        fcd_df = pd.read_parquet(io.BytesIO(fcd_bytes))
        gdf2 = gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
        _, stats_joined = svc.run_full_pipeline(gdf2, fcd_df=fcd_df)
        assert stats_joined["fcd_joined"] is True
        assert stats_joined["fcd_columns_count"] >= 3
        # Apres jointure, FCD_TV_cliff doit etre detecte (chaine A/C du reseau).
        assert stats_joined["n_causes"].get("FCD_TV_cliff", 0) >= 1


# ---------------------------------------------------------------------------
# Tests upload-fcd + integration analyze
# ---------------------------------------------------------------------------


class TestUploadFcd:
    @pytest.mark.asyncio
    async def test_upload_fcd_happy_path(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        assert up.status_code == 200, up.text
        sid = up.json()["session_id"]

        fcd_bytes = _build_fcd_parquet_bytes(_synthetic_network())
        r = await authenticated_client.post(
            "/api/discontinuites/upload-fcd",
            files={"file": ("fcd.parquet", fcd_bytes, "application/octet-stream")},
            data={"session_id": sid},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["session_id"] == sid
        assert body["n_segments"] == 10
        # Toutes les colonnes FCD attendues doivent etre detectees.
        assert "TMJOFCDTV" in body["columns_detected"]
        assert "TMJOFCDPL" in body["columns_detected"]
        assert body["file_size_mb"] > 0

    @pytest.mark.asyncio
    async def test_upload_fcd_without_geojson_returns_400(self, authenticated_client, tmp_workspace, owned_session_id):
        # owned_session_id existe mais aucun segments.geojson n'a ete uploade.
        fcd_bytes = _build_fcd_parquet_bytes(_synthetic_network())
        r = await authenticated_client.post(
            "/api/discontinuites/upload-fcd",
            files={"file": ("fcd.parquet", fcd_bytes, "application/octet-stream")},
            data={"session_id": owned_session_id},
        )
        assert r.status_code == 400
        assert "geojson" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_fcd_wrong_extension_returns_400(self, authenticated_client, tmp_workspace):
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        sid = up.json()["session_id"]

        r = await authenticated_client.post(
            "/api/discontinuites/upload-fcd",
            files={"file": ("fcd.csv", b"a,b\n1,2", "text/csv")},
            data={"session_id": sid},
        )
        assert r.status_code == 400
        assert ".parquet" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_fcd_missing_required_column_returns_400(
        self, authenticated_client, tmp_workspace
    ):
        import pandas as pd

        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("network.geojson", _synthetic_geojson_str(), "application/geo+json")},
        )
        sid = up.json()["session_id"]

        df = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})  # pas de segment_id
        buf = io.BytesIO()
        df.to_parquet(buf, engine="pyarrow")
        r = await authenticated_client.post(
            "/api/discontinuites/upload-fcd",
            files={"file": ("bad.parquet", buf.getvalue(), "application/octet-stream")},
            data={"session_id": sid},
        )
        assert r.status_code == 400
        assert "segment_id" in r.json()["detail"]


class TestAnalyzeWithFcdJoin:
    @pytest.mark.asyncio
    async def test_analyze_without_fcd_returns_warning(self, authenticated_client, tmp_workspace):
        """Sur un reseau light (sans FCD), /analyze doit signaler le mode degrade."""
        light_str = json.dumps(_light_network())
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("light.geojson", light_str, "application/geo+json")},
        )
        assert up.status_code == 200, up.text
        sid = up.json()["session_id"]

        r = await authenticated_client.post(
            "/api/discontinuites/analyze",
            data={"session_id": sid},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fcd_joined"] is False
        assert body["fcd_columns_count"] == 0
        # Warning attendu : la majorite des noeuds tombe en Coverage_gap.
        assert body.get("warning") is not None
        assert "FCD" in body["warning"]

    @pytest.mark.asyncio
    async def test_analyze_with_fcd_restores_classification(self, authenticated_client, tmp_workspace):
        """Avec parquet FCD joint, FCD_TV_cliff doit reapparaitre dans la distribution."""
        # Reseau light en geojson
        light_str = json.dumps(_light_network())
        up = await authenticated_client.post(
            "/api/discontinuites/upload-geojson",
            files={"file": ("light.geojson", light_str, "application/geo+json")},
        )
        sid = up.json()["session_id"]

        # Upload FCD ref calibre
        fcd_bytes = _build_fcd_parquet_bytes(_synthetic_network())
        uf = await authenticated_client.post(
            "/api/discontinuites/upload-fcd",
            files={"file": ("fcd.parquet", fcd_bytes, "application/octet-stream")},
            data={"session_id": sid},
        )
        assert uf.status_code == 200, uf.text

        # Re-analyze
        r = await authenticated_client.post(
            "/api/discontinuites/analyze",
            data={"session_id": sid},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["fcd_joined"] is True
        assert body["fcd_columns_count"] >= 3
        assert body.get("warning") is None
        # FCD_TV_cliff doit etre present (chaine A/C du reseau a un fort ratio).
        assert body["n_causes"].get("FCD_TV_cliff", 0) >= 1

        # Stats endpoint expose aussi fcd_*
        st = await authenticated_client.get(f"/api/discontinuites/stats/{sid}")
        assert st.status_code == 200, st.text
        stats_body = st.json()
        assert stats_body["fcd_joined"] is True
        assert stats_body["fcd_matched"] >= 1
        assert "TMJOFCDTV" in stats_body["fcd_columns"]
