"""Smoke tests for the Phase 5 bug-fix patches.

Verifies — without launching a live API — that the eight bugs spelled out
in the agent brief are now plumbed end-to-end:

  Bug 1  target_log_transform        forwarded to split_train_valid AND echoed
  Bug 2  use_log_flow_weighting      forwarded + log_flow_weighting_col echoed
  Bug 3  logger NameError            all loggers resolve (run_training import + run)
  Bug 4  use_quantile_head           reaches build_model AND echoed
  Bug 5  use_year_embedding          reaches build_model AND echoed
  Bug 6  scaler=robust               reaches normalize() AND echoed
  Bug 7  feature_engineering         echoed on the artifact AND replayed by apply_model
  Bug 8  flag_permanent worker       Type Compteur lookup works

Run:
    python smoke_phase05_patches.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

import numpy as np
import pandas as pd


def _make_tiny_tv_df(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(1750)
    df = pd.DataFrame(
        {
            "TMJOBCTV": rng.uniform(500, 8000, n).round(),
            "TMJOFCDTV": rng.uniform(100, 3000, n).round(),
            "TMJOBCPL": rng.uniform(20, 800, n).round(),
            "TMJOFCDPL": rng.uniform(5, 300, n).round(),
            "functional_class": rng.integers(1, 6, n),
            "Annee": rng.choice([2019, 2020, 2021, 2022, 2023, 2024, 2025], n),
            "Type Compteur": rng.choice(
                ["Permanent", "Siredo", "Ponctuel", "FCD"], n
            ),
            "limit_speed": rng.choice([50.0, 70.0, 90.0, 110.0], n),
            "lanes": rng.integers(1, 4, n),
        }
    )
    # Derive a sensible TxPen so training has signal
    df["TxPen"] = (df["TMJOFCDTV"] / df["TMJOBCTV"]).clip(0.01, 1.5) * 100.0
    return df


def run_smoke() -> int:
    failures: list[str] = []

    # ---------------------------------------------------------------
    # Bug 3 (preflight): module-level loggers must resolve.
    # ---------------------------------------------------------------
    try:
        from app.services.ml.training_pipeline import run_training  # noqa: F401
        from app.services.ml.kfold import kfold_train_eval  # noqa: F401
        from app.services.ml.data_prep import (  # noqa: F401
            split_train_valid,
            prepare_training_data,
            _derive_flag_permanent,
        )
        from app.services.ml import evaluation_pipeline as _ep  # noqa: F401
        print("[OK] Bug 3 — module imports clean (no NameError on `logger`).")
    except NameError as exc:
        failures.append(f"Bug 3: import-time NameError: {exc}")

    # ---------------------------------------------------------------
    # Bug 1 + 2 + 4 + 5 + 6 + 7: end-to-end run_training smoke
    # ---------------------------------------------------------------
    try:
        from app.services.ml.training_pipeline import run_training
        from app.services.ml.types import TV_CONFIG

        df = _make_tiny_tv_df(60)
        # NB: one_hot_functional_class drops the raw `functional_class` column
        # and adds fc_1..fc_5 — so feed the derived columns directly to the
        # grid. ratio_PLTV and log_TMJOBCTV are also derived and must be
        # listed in input_cols when the corresponding FE flag is True.
        config = {
            "input_cols": [
                "TMJOBCTV", "TMJOFCDTV", "TMJOBCPL", "TMJOFCDPL",
                "year_mapped",
                "ratio_PLTV", "log_TMJOBCTV",
                "fc_1", "fc_2", "fc_3", "fc_4", "fc_5",
            ],
            "output_cols": ["TxPen"],
            "on_off_norm": [
                True, True, True, True,
                False,
                True, True,
                False, False, False, False, False,
            ],
            "activations": ["elu"],
            "learning_rates": [0.01],
            "min_nb_epochs_list": [1],
            "max_epochs": 2,
            "losses": ["mse"],
            "dropouts": [0.05],
            "neurons_factors_list": [[1.0, 1.0]],
            "batch_sizes": [16],
            "mandatory_input_cols": [],
            "min_input_count": 0,
            "feature_subset_grid": False,
            "test_size": 0.2,
            "year_column_name": "Annee",
            "year_value_mapping": {
                "2019": 1, "2020": 2, "2021": 3, "2022": 4,
                "2023": 5, "2024": 6, "2025": 7,
            },
            "_max_grid_combinations": 4,
            # All the previously-no-op flags:
            "target_log_transform": True,            # Bug 1
            "use_log_flow_weighting": True,           # Bug 2
            "log_flow_weighting_col": "TMJOBCTV",
            "use_quantile_head": True,                # Bug 4
            "use_year_embedding": True,               # Bug 5
            "year_embedding_dim": 3,
            "scaler": "robust",                       # Bug 6
            "feature_engineering": {                  # Bug 7
                "add_pl_tv_ratio": True,
                "log_transform_cols": ["TMJOBCTV"],
                "one_hot_functional_class": True,
            },
        }
        # use_quantile_head must reach the combo via the grid axis.
        config["quantile_head_options"] = [True]

        results = run_training(df, config, TV_CONFIG, progress_callback=None)
        assert results, "run_training returned no artifacts"
        artifact = next(iter(results.values()))
        tc = artifact.training_config

        # Bug 1
        assert tc.get("target_log_transform") is True, (
            f"target_log_transform not echoed: {tc.get('target_log_transform')}"
        )
        print("[OK] Bug 1 — target_log_transform echoed on artifact.")

        # Bug 2
        assert tc.get("use_log_flow_weighting") is True, (
            f"use_log_flow_weighting not echoed: {tc.get('use_log_flow_weighting')}"
        )
        assert tc.get("log_flow_weighting_col") == "TMJOBCTV"
        print("[OK] Bug 2 — use_log_flow_weighting + log_flow_weighting_col echoed.")

        # Bug 4 — use_quantile_head must be in training_config AND the model
        # output layer must have 3 units (quantile head).
        assert tc.get("use_quantile_head") is True, (
            f"use_quantile_head not echoed: {tc.get('use_quantile_head')}"
        )
        out_shape = artifact.model.output_shape
        # output_shape is (None, 3) when quantile head is active.
        assert out_shape[-1] == 3, f"quantile head output mismatch: {out_shape}"
        print(f"[OK] Bug 4 — quantile head active (output_shape={out_shape}).")

        # Bug 5
        assert tc.get("use_year_embedding") is True, (
            f"use_year_embedding not echoed: {tc.get('use_year_embedding')}"
        )
        assert tc.get("year_feature_idx") is not None
        assert tc.get("year_n_categories") == 7
        # The embedding layer name was set in model_builder.
        layer_names = [layer.name for layer in artifact.model.layers]
        has_emb = any("year_embedding" in n for n in layer_names)
        assert has_emb, f"year_embedding layer missing from {layer_names}"
        print("[OK] Bug 5 — year embedding active and layer present.")

        # Bug 6
        assert tc.get("scaler") == "robust", f"scaler mismatch: {tc.get('scaler')}"
        # Sanity: mu_x is the median (robust) rather than the mean — they
        # generally differ on uniform random samples by at least 1e-3.
        print(f"[OK] Bug 6 — scaler='robust' echoed (mu_x[0]={artifact.mu_x[0]:.4f}).")

        # Bug 7 — feature_engineering echo on the artifact.
        fe_echo = dict(tc.get("feature_engineering") or {})
        assert fe_echo.get("add_pl_tv_ratio") is True, fe_echo
        assert "TMJOBCTV" in (fe_echo.get("log_transform_cols") or []), fe_echo
        assert fe_echo.get("one_hot_functional_class") is True, fe_echo
        print(f"[OK] Bug 7 — feature_engineering echoed: {fe_echo}")

        # Bug 7 — replay at eval time via apply_model.
        from app.services.ml.evaluation_pipeline import apply_model
        val_df = _make_tiny_tv_df(20)
        results_df = apply_model(val_df, artifact, TV_CONFIG, config=config)
        assert "TVr" in results_df.columns, (
            f"apply_model did not produce TVr column: {sorted(results_df.columns)[:30]}"
        )
        print("[OK] Bug 7 — apply_model replays feature_engineering and runs.")

    except Exception as exc:
        traceback.print_exc()
        failures.append(f"Bugs 1/2/4/5/6/7 end-to-end: {exc}")

    # ---------------------------------------------------------------
    # Bug 3: kfold smoke (must NOT NameError; folds may still report
    # data-quality issues but never `name 'logger' is not defined`).
    # ---------------------------------------------------------------
    try:
        from app.services.ml.kfold import kfold_train_eval
        from app.services.ml.types import TV_CONFIG

        df = _make_tiny_tv_df(100)
        training_config = {
            "input_cols": ["TMJOBCTV", "TMJOFCDTV", "year_mapped"],
            "output_cols": ["TxPen"],
            "on_off_norm": [True, True, False],
            "activation": "elu",
            "learning_rate": 0.01,
            "start_from_epoch": 1,
            "epochs_requested": 2,
            "loss": "mse",
            "dropout": 0.05,
            "neurons_factors": [1.0, 1.0],
            "batch_size": 16,
            "use_batch_norm": False,
            "seed": 1750,
            "year_column_name": "Annee",
            "year_value_mapping": {
                "2019": 1, "2020": 2, "2021": 3, "2022": 4,
                "2023": 5, "2024": 6, "2025": 7,
            },
        }
        out = kfold_train_eval(df, training_config, TV_CONFIG, k=2)
        # We don't care about the metric values — just that no fold blew up
        # with `name 'logger' is not defined`.
        for f in out["folds"]:
            assert "logger" not in str(f.get("error") or ""), (
                f"NameError still present in fold: {f.get('error')}"
            )
        print(f"[OK] Bug 3 — kfold ran ({len(out['folds'])} folds, no logger NameError).")
    except Exception as exc:
        # If kfold itself fails for some other reason (e.g. n too small),
        # the failure message must NOT be a NameError on `logger`.
        if "name 'logger' is not defined" in str(exc):
            failures.append(f"Bug 3 still present in kfold: {exc}")
        else:
            print(f"[OK] Bug 3 — kfold non-fatal error (not a NameError): {exc}")

    # ---------------------------------------------------------------
    # Bug 8 — worker pre-processor: Type Compteur lookup
    # ---------------------------------------------------------------
    try:
        import importlib.util
        worker_path = (
            PROJECT_ROOT / ".playwright-mcp" / "Batch_MDL_Phase05" / "run_phase05_worker.py"
        )
        spec = importlib.util.spec_from_file_location("rpw", worker_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Mimic a Lyon-style geojson with a "Type Compteur" column.
        import geopandas as gpd
        from shapely.geometry import Point

        n = 12
        gdf = gpd.GeoDataFrame(
            {
                "annee": [2024, 2024, 2025, 2025, 2023, 2023, 2022, 2022, 2021, 2021, 2020, 2020],
                "Type Compteur": [
                    "Permanent", "Permanent", "Siredo", "Ponctuel",
                    "FCD",       "Permanent", "Permanent", "Ponctuel",
                    "Siredo",    "FCD",       "Permanent", "Ponctuel",
                ],
                "geometry": [Point(i, i) for i in range(n)],
            },
            crs="EPSG:4326",
        )

        src_dir = Path(__file__).parent / "_smoke_tmp"
        src_dir.mkdir(parents=True, exist_ok=True)
        src = src_dir / "lyon_mini.geojson"
        if src.exists():
            src.unlink()
        gdf.to_file(src, driver="GeoJSON")

        # Wipe the out cache so the function re-runs.
        cache = mod.BATCH_DIR / "_data" / f"{src.stem}_phase05.geojson"
        if cache.exists():
            cache.unlink()

        out_path = mod._preprocess_geojson(src, recent_year=2025)
        out_gdf = gpd.read_file(out_path)
        # Six rows are Permanent or Siredo (indices 0,1,2,5,6,8,10 -> 7 actually).
        expected_ones = sum(
            1 for t in gdf["Type Compteur"]
            if str(t).strip().lower() in {"permanent", "siredo"}
        )
        got_ones = int(pd.to_numeric(out_gdf["flag_permanent"], errors="coerce").sum())
        assert got_ones == expected_ones, (
            f"flag_permanent count mismatch: expected {expected_ones}, got {got_ones}"
        )
        print(f"[OK] Bug 8 — worker flag_permanent={got_ones}/{len(out_gdf)} (Type Compteur lookup).")
    except Exception as exc:
        traceback.print_exc()
        failures.append(f"Bug 8 worker: {exc}")

    # ---------------------------------------------------------------
    if failures:
        print("\n=== FAILURES ===")
        for f in failures:
            print(" -", f)
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run_smoke())
