"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import type {
  CarteGenerateResponse,
  CarteStats,
  HourlySaturationConfig,
  PlSaturationConfig,
} from "@/lib/carte/types";

// ---------------------------------------------------------------------------
// useCarteGeneration — encapsule le POST /api/carte/generate
// ---------------------------------------------------------------------------
// Le payload contient ~43 champs. En groupant les inputs en objets stables
// (models, mapping, filters, saturations), on ramene les dependances de
// useCallback a 6 entrees seulement (vs 43 dans l'inline d'origine).
// Comportement strictement identique : meme timeout 5 min, memes toasts.
// ---------------------------------------------------------------------------

export interface CarteGenerationModels {
  modelTvDir: string;
  modelPlDir: string;
  modelHpmDir: string;
  modelHpsDir: string;
}

export interface CarteGenerationFilters {
  filterTvrEnabled: boolean;
  filterTvrValue: number;
  filterFcEnabled: boolean;
  // Tranches IC v/j (D2)
  err01000: number;
  err10002000: number;
  err20004000: number;
  err4000plus: number;
  // Tranches IC v/h PM
  errPm0100: number;
  errPm100300: number;
  errPm300600: number;
  errPm600plus: number;
  // Tranches IC v/h PS
  errPs0100: number;
  errPs100300: number;
  errPs300600: number;
  errPs600plus: number;
  // Arrondi progressif
  arrondiEnabled: boolean;
}

export interface CarteGenerationSaturations {
  pl: PlSaturationConfig;
  hpm: HourlySaturationConfig;
  hps: HourlySaturationConfig;
}

export interface UseCarteGenerationOptions {
  sessionId: string | null;
  models: CarteGenerationModels;
  mapping: Record<string, string | null>;
  filters: CarteGenerationFilters;
  saturations: CarteGenerationSaturations;
  canGenerate: boolean;
  /**
   * Dedicated year mapping (split from the regular column_mapping). The backend
   * derives ``year_mapped`` from ``year_column_name`` via ``year_value_mapping``.
   * Both are null when no loaded model uses the year feature.
   */
  yearColumnName: string | null;
  yearValueMapping: Record<string, number> | null;
}

export interface UseCarteGenerationReturn {
  generate: () => Promise<void>;
  generating: boolean;
  progress: number;
  progressText: string;
  done: boolean;
  stats: CarteStats | null;
  /** Reinitialise done + stats (utilise par le parent quand le FCD est retire). */
  resetResults: () => void;
}

export function useCarteGeneration(
  opts: UseCarteGenerationOptions,
): UseCarteGenerationReturn {
  const {
    sessionId,
    models,
    mapping,
    filters,
    saturations,
    canGenerate,
    yearColumnName,
    yearValueMapping,
  } = opts;

  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [done, setDone] = useState(false);
  const [stats, setStats] = useState<CarteStats | null>(null);

  const generate = useCallback(async () => {
    if (!canGenerate || !sessionId) return;
    setGenerating(true);
    setDone(false);
    setStats(null);
    setProgress(10);
    setProgressText("Chargement des modeles...");

    try {
      setProgress(30);
      setProgressText("Application des modeles TV et PL...");

      const pl = saturations.pl;
      const hpm = saturations.hpm;
      const hps = saturations.hps;

      // Carte generation peut prendre 30s-5min selon taille dataset (241k segments Lyon ~ 37s).
      // Default apiClient timeoutMs=30s coupe la connexion -> AbortError silencieux.
      const res = await apiClient.post<CarteGenerateResponse>(
        "/api/carte/generate",
        {
          session_id: sessionId,
          model_tv_dir: models.modelTvDir,
          // Optional models — null when the user didn't upload them. The
          // backend treats null/missing as "skip this output". PL is now
          // optional like HPM/HPS : null => no PL outputs (DPL/DPLmin/DPLmax
          // and derived PLr*/PLred/VLred are not produced).
          model_pl_dir: models.modelPlDir || null,
          model_hpm_dir: models.modelHpmDir || null,
          model_hps_dir: models.modelHpsDir || null,
          column_mapping: mapping,
          // Dedicated year handling — the backend computes year_mapped from
          // df[year_column_name].map(year_value_mapping). Both null when no
          // loaded model uses the year feature (contract agreed with backend).
          year_column_name: yearColumnName,
          year_value_mapping: yearValueMapping,
          filter_tvr_enabled: filters.filterTvrEnabled,
          filter_tvr_value: filters.filterTvrValue,
          filter_fc_enabled: filters.filterFcEnabled,
          error_thresholds: {
            err_0_1000: filters.err01000 / 100,
            err_1000_2000: filters.err10002000 / 100,
            err_2000_4000: filters.err20004000 / 100,
            err_4000_plus: filters.err4000plus / 100,
          },
          // v/h tranches for HPM (PM*) and HPS (PS*) — sent as percentage
          // values directly (NOT divided by 100), matching the backend
          // ``PeakHourErrorThresholds`` Pydantic schema (err_0_100 = 25.0
          // means "25%"). Backend silently uses defaults if these are
          // omitted, but defaults match initial state so they round-trip.
          err_pm_thresholds: {
            err_0_100: filters.errPm0100,
            err_100_300: filters.errPm100300,
            err_300_600: filters.errPm300600,
            err_600_plus: filters.errPm600plus,
          },
          err_ps_thresholds: {
            err_0_100: filters.errPs0100,
            err_100_300: filters.errPs100300,
            err_300_600: filters.errPs300600,
            err_600_plus: filters.errPs600plus,
          },
          // --- Saturation hierarchique PL (v2 hybride adaptative) ---
          // Voir SATURATION_PL_specs.md v2. Toggle OFF => le backend doit
          // ignorer les caps et renvoyer les predictions brutes.
          // - bornes_fc_abs : cap absolu PL/jour par FC (renamed v1 bornes_fc)
          // - alpha_fc_min  : plancher du ratio PL/JOr par FC (renamed v1 alpha_fc)
          //                   envoye en ratio (0..1), pas en %.
          // - ratio_macro_pen, alpha_physique_max, seuil_vol_fcd_tv :
          //   nouveaux hyperparamètres v2 hybride adaptative.
          pl_saturation_enabled: pl.enabled,
          bornes_fc_abs: {
            1: pl.bornesFc1,
            2: pl.bornesFc2,
            3: pl.bornesFc3,
            4: pl.bornesFc4,
            5: pl.bornesFc5,
          },
          alpha_fc_min: {
            1: pl.alphaFc1 / 100,
            2: pl.alphaFc2 / 100,
            3: pl.alphaFc3 / 100,
            4: pl.alphaFc4 / 100,
            5: pl.alphaFc5 / 100,
          },
          ratio_macro_pen: pl.ratioMacroPen,
          alpha_physique_max: pl.alphaPhysiqueMax / 100,
          seuil_vol_fcd_tv: pl.seuilVolFcdTv,
          // --- v3 zones critiques (override capteurs SIREDO PL) ---
          // Voir SATURATION_PL_specs.md v3 §"Override zones critiques".
          // Si capteurs_pl_session_id null OU zone_critique_enabled false =>
          // backend fait un fallback silencieux v2 (pas de zones critiques).
          // Ratios saisis en % cote UI => divises par 100 dans le payload.
          zone_critique_enabled: pl.zoneCritEnabled,
          capteurs_pl_session_id: pl.capteursPlSessionId,
          annee_capteurs: pl.anneeCapteurs,
          ratio_capteur_critique: pl.ratioCapteurCritique / 100,
          buffer_zone_critique_m: pl.bufferZoneCritiqueM,
          alpha_min_zone_critique: pl.alphaMinZoneCritique / 100,
          // --- Saturation hierarchique HPM (heure de pointe matin) ---
          // Voir SATURATION_HPM_HPS_specs.md. Caps val/h + ratio max PM/JOr.
          // ALPHA_HPM_FC envoye en ratio (0..1), pas en pourcentage.
          hpm_saturation_enabled: hpm.enabled,
          borne_hpm_fc: {
            1: hpm.borneFc1,
            2: hpm.borneFc2,
            3: hpm.borneFc3,
            4: hpm.borneFc4,
            5: hpm.borneFc5,
          },
          alpha_hpm_fc: {
            1: hpm.alphaFc1 / 100,
            2: hpm.alphaFc2 / 100,
            3: hpm.alphaFc3 / 100,
            4: hpm.alphaFc4 / 100,
            5: hpm.alphaFc5 / 100,
          },
          // --- Saturation hierarchique HPS (heure de pointe soir) ---
          hps_saturation_enabled: hps.enabled,
          borne_hps_fc: {
            1: hps.borneFc1,
            2: hps.borneFc2,
            3: hps.borneFc3,
            4: hps.borneFc4,
            5: hps.borneFc5,
          },
          alpha_hps_fc: {
            1: hps.alphaFc1 / 100,
            2: hps.alphaFc2 / 100,
            3: hps.alphaFc3 / 100,
            4: hps.alphaFc4 / 100,
            5: hps.alphaFc5 / 100,
          },
          // --- Arrondi progressif (ARRONDI_PROGRESSIF_specs.md) ---
          // Arrondit JOr/DPL/PM/PS (+ IC min/max) selon 3 paliers (5/10/100).
          arrondi_progressif_enabled: filters.arrondiEnabled,
        },
        { timeoutMs: 5 * 60_000 },
      );

      setProgress(100);
      setProgressText("Generation terminee !");
      setStats(res.stats);
      setDone(true);
      const _tvrMoy =
        res.stats.mean_tvr != null
          ? `, JOr moyen: ${Math.round(res.stats.mean_tvr).toLocaleString("fr-FR")} veh/j`
          : "";
      toast.success(
        `Carte generee — ${res.geojson_feature_count.toLocaleString("fr-FR")} troncons${_tvrMoy}`,
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      const isAbort =
        message.toLowerCase().includes("abort") ||
        message.toLowerCase().includes("timeout");
      const userMessage = isAbort
        ? "La generation a depasse le delai (timeout). Reessayez ou reduisez la taille du jeu FCD."
        : `Erreur generation : ${message}`;
      toast.error(userMessage);
      setProgress(0);
      setProgressText("");
    } finally {
      setGenerating(false);
    }
  }, [canGenerate, sessionId, models, mapping, filters, saturations, yearColumnName, yearValueMapping]);

  const resetResults = useCallback(() => {
    setDone(false);
    setStats(null);
  }, []);

  return { generate, generating, progress, progressText, done, stats, resetResults };
}
