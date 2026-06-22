"""Tests for HPM / HPS peak-hour helpers (audit T2 § "Tests critiques manquants").

Couvre :
  - `_peak_hour_err_pct` : tranches de l'IC v/h (0-100/100-300/300-600/>600).
  - `_ensure_hourly_fcd_column` : alias FCDTV_h08 -> FCD_HPM_TV et idem HPS.
  - `derive_hpm_hps_columns` (services.ml.data_prep) : derivation FCD horaire
    et TxPen horaire (pipeline cote training).

Imports : nouveau chemin `app.services.ml.saturation` si dispo (autre agent),
sinon fallback `app.routers.carte`. Pour `derive_hpm_hps_columns`, source
canonique reste `app.services.ml.data_prep`.
"""

from __future__ import annotations

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Imports avec fallback
# ---------------------------------------------------------------------------

try:
    from app.services.ml.saturation import (
        PeakHourErrorThresholds,
        _ensure_hourly_fcd_column,
        _peak_hour_err_pct,
    )
except ImportError:
    from app.routers.carte import (
        PeakHourErrorThresholds,
        _ensure_hourly_fcd_column,
        _peak_hour_err_pct,
    )

# derive_hpm_hps_columns vit dans data_prep (pipeline training).
from app.services.ml.data_prep import derive_hpm_hps_columns

# ---------------------------------------------------------------------------
# _peak_hour_err_pct - tranches v/h
# ---------------------------------------------------------------------------


class TestPeakHourErrPctTranches:
    """Tranches d'IC en v/h (cf PeakHourErrorThresholds defaults D2)."""

    def test_peak_hour_err_pct_tranche_0_100(self):
        thr = PeakHourErrorThresholds()
        # 50 v/h -> tranche 0-100 = 25%
        assert _peak_hour_err_pct(50.0, thr) == 25.0
        assert _peak_hour_err_pct(0.0, thr) == 25.0
        assert _peak_hour_err_pct(99.99, thr) == 25.0

    def test_peak_hour_err_pct_tranche_100_300(self):
        thr = PeakHourErrorThresholds()
        # 200 v/h -> tranche 100-300 = 18%
        assert _peak_hour_err_pct(100.0, thr) == 18.0
        assert _peak_hour_err_pct(200.0, thr) == 18.0
        assert _peak_hour_err_pct(299.99, thr) == 18.0

    def test_peak_hour_err_pct_tranche_300_600(self):
        thr = PeakHourErrorThresholds()
        # 450 v/h -> tranche 300-600 = 18%
        assert _peak_hour_err_pct(300.0, thr) == 18.0
        assert _peak_hour_err_pct(450.0, thr) == 18.0
        assert _peak_hour_err_pct(599.99, thr) == 18.0

    def test_peak_hour_err_pct_tranche_600_plus(self):
        thr = PeakHourErrorThresholds()
        # 1000 v/h -> tranche >600 = 14%
        assert _peak_hour_err_pct(600.0, thr) == 14.0
        assert _peak_hour_err_pct(1000.0, thr) == 14.0
        assert _peak_hour_err_pct(99999.0, thr) == 14.0


# ---------------------------------------------------------------------------
# _ensure_hourly_fcd_column - aliases FCDTV_h08 -> FCD_HPM_TV (et HPS)
# ---------------------------------------------------------------------------


class TestEnsureHourlyFcdColumnAlias:
    """Materialise FCD_HPM_TV / FCD_HPS_TV depuis leurs aliases sources."""

    def test_canonical_already_present_noop(self):
        """Si la colonne canonique est deja la, ne touche pas."""
        df = pd.DataFrame({"FCD_HPM_TV": [10, 20, 30]})
        out = _ensure_hourly_fcd_column(
            df,
            "FCD_HPM_TV",
            ("FCDTV_h08",),
            "HPM",
        )
        assert "FCD_HPM_TV" in out.columns
        assert list(out["FCD_HPM_TV"]) == [10, 20, 30]

    def test_alias_h08_to_fcd_hpm_tv(self):
        """FCDTV_h08 -> FCD_HPM_TV."""
        df = pd.DataFrame({"FCDTV_h08": [100, 200, 300]})
        out = _ensure_hourly_fcd_column(
            df,
            "FCD_HPM_TV",
            ("FCDTV_h08", "FCDTV_HPM"),
            "HPM",
        )
        assert "FCD_HPM_TV" in out.columns
        assert list(out["FCD_HPM_TV"]) == [100, 200, 300]

    def test_alias_h17_to_fcd_hps_tv(self):
        """FCDTV_h17 -> FCD_HPS_TV."""
        df = pd.DataFrame({"FCDTV_h17": [50, 80, 90]})
        out = _ensure_hourly_fcd_column(
            df,
            "FCD_HPS_TV",
            ("FCDTV_h17", "FCDTV_HPS"),
            "HPS",
        )
        assert "FCD_HPS_TV" in out.columns
        assert list(out["FCD_HPS_TV"]) == [50, 80, 90]

    def test_missing_all_raises_400(self):
        """Ni canonique ni alias -> HTTPException 400."""
        from fastapi import HTTPException

        df = pd.DataFrame({"unrelated_col": [1, 2]})
        with pytest.raises(HTTPException) as exc:
            _ensure_hourly_fcd_column(
                df,
                "FCD_HPM_TV",
                ("FCDTV_h08", "FCDTV_HPM"),
                "HPM",
            )
        assert exc.value.status_code == 400

    def test_first_matching_alias_wins(self):
        """Si plusieurs aliases sont presents, on prend le premier de l'ordre fourni."""
        df = pd.DataFrame({"FCDTV_h08": [1, 2, 3], "FCDTV_HPM": [10, 20, 30]})
        out = _ensure_hourly_fcd_column(
            df,
            "FCD_HPM_TV",
            ("FCDTV_h08", "FCDTV_HPM"),
            "HPM",
        )
        # FCDTV_h08 est premier dans l'ordre des alias -> doit etre selectionne
        assert list(out["FCD_HPM_TV"]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# derive_hpm_hps_columns (pipeline training)
# ---------------------------------------------------------------------------


class TestDeriveHpmHpsColumns:
    """Pipeline training : derive FCD/TxPen horaires depuis colonnes brutes."""

    def test_fcd_hpm_tv_derived_from_fcdtv_h08(self):
        """FCD_HPM_TV materialise depuis FCDTV_h08 si absent."""
        df = pd.DataFrame(
            {
                "FCDTV_h08": [100.0, 200.0, 300.0],
                "FCDTV_h17": [50.0, 80.0, 90.0],
            }
        )
        out = derive_hpm_hps_columns(df.copy())
        assert "FCD_HPM_TV" in out.columns
        assert "FCD_HPS_TV" in out.columns
        # Numeric: peut etre float
        assert out["FCD_HPM_TV"].iloc[0] == pytest.approx(100.0)
        assert out["FCD_HPS_TV"].iloc[1] == pytest.approx(80.0)

    def test_txpen_hpm_computed_when_bc_available(self):
        """TxPen_HPM = FCD_HPM_TV / TMJOBCTV_HPM * 100 quand BC dispo."""
        df = pd.DataFrame(
            {
                "FCD_HPM_TV": [100.0, 200.0],
                "TMJOBCTV_HPM": [500.0, 1000.0],
            }
        )
        out = derive_hpm_hps_columns(df.copy())
        # 100/500*100 = 20 ; 200/1000*100 = 20
        assert out["TxPen_HPM"].iloc[0] == pytest.approx(20.0)
        assert out["TxPen_HPM"].iloc[1] == pytest.approx(20.0)

    def test_txpen_hps_computed_when_bc_available(self):
        """Symetrique HPS."""
        df = pd.DataFrame(
            {
                "FCD_HPS_TV": [60.0],
                "TMJOBCTV_HPS": [600.0],
            }
        )
        out = derive_hpm_hps_columns(df.copy())
        # 60/600*100 = 10
        assert out["TxPen_HPS"].iloc[0] == pytest.approx(10.0)

    def test_existing_columns_not_overwritten(self):
        """Les colonnes deja presentes ne sont pas reecrites."""
        df = pd.DataFrame(
            {
                "FCD_HPM_TV": [999.0],
                "FCDTV_h08": [100.0],
                "TxPen_HPM": [55.0],
                "TMJOBCTV_HPM": [200.0],
            }
        )
        out = derive_hpm_hps_columns(df.copy())
        # FCD_HPM_TV et TxPen_HPM doivent rester intacts
        assert out["FCD_HPM_TV"].iloc[0] == 999.0
        assert out["TxPen_HPM"].iloc[0] == 55.0


# ---------------------------------------------------------------------------
# Smoke : pipeline complet HPM/HPS (predict_peak_hour est asynchrone, on
# n'a pas le modele TF ici - on couvre seulement les helpers de prep).
# ---------------------------------------------------------------------------


class TestPredictPeakHourSmoke:
    """Pas de TF disponible dans les tests CI -> on smoke-test les helpers
    de preparation seulement. Le model.predict() etant cible par les tests
    e2e separes."""

    def test_predict_peak_hour_hpm_helpers_chain(self):
        """Verifie que la chaine de prep (alias + derivation FCD) tourne
        sur des donnees HPM minimalistes sans crash."""
        df = pd.DataFrame(
            {
                "FCDTV_h08": [120.0, 200.0],
                "TMJOFCDPL": [10.0, 20.0],
            }
        )
        out = _ensure_hourly_fcd_column(
            df,
            "FCD_HPM_TV",
            ("FCDTV_h08", "FCDTV_HPM", "FCD_HPM"),
            "HPM",
        )
        assert "FCD_HPM_TV" in out.columns
        # Numeric : float
        assert pd.api.types.is_numeric_dtype(out["FCD_HPM_TV"])

    def test_predict_peak_hour_hps_helpers_chain(self):
        """Idem pour HPS."""
        df = pd.DataFrame(
            {
                "FCDTV_h17": [60.0, 90.0],
                "TMJOFCDPL": [5.0, 8.0],
            }
        )
        out = _ensure_hourly_fcd_column(
            df,
            "FCD_HPS_TV",
            ("FCDTV_h17", "FCDTV_HPS", "FCD_HPS"),
            "HPS",
        )
        assert "FCD_HPS_TV" in out.columns
        assert pd.api.types.is_numeric_dtype(out["FCD_HPS_TV"])
