"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  ArrowLeft,
  Car,
  Download,
  Filter,
  Layers,
  Map,
  Sunrise,
  Sunset,
  Truck,
} from "lucide-react";
import { toast } from "sonner";
import { AuroraBg } from "@/components/backgrounds/aurora-bg";
import { GlowCard } from "@/components/ui/glow-card";
import { GradientText } from "@/components/ui/gradient-text";
import { NeonButton } from "@/components/ui/neon-button";
// UX5 — composants premium pour CTA result + badges KPI carte generee
import {
  MagneticButton,
  ShimmerText,
  StatBadge,
  RevealOnScroll,
  NeonBorder,
} from "@/components/ui";
import { useAppStore } from "@/lib/store";
import { apiClient, uploadFile } from "@/lib/api";
import { FcdUploadSection } from "@/components/carte/FcdUploadSection";
import { ModelUploadSection } from "@/components/carte/ModelUploadSection";
import { PlSaturationPanel } from "@/components/carte/PlSaturationPanel";
import { HourlySaturationPanel } from "@/components/carte/HourlySaturationPanel";
import {
  ArrondiToggleCard,
  FiltersSection,
} from "@/components/carte/FiltersSection";
import { GenerationSection } from "@/components/carte/GenerationSection";
import {
  HPM_SAT_ALPHA_DEFAULTS,
  HPM_SAT_BORNES_DEFAULTS,
  HPS_SAT_ALPHA_DEFAULTS,
  HPS_SAT_BORNES_DEFAULTS,
  PL_SAT_ALPHA_DEFAULTS,
  PL_SAT_BORNES_DEFAULTS,
  PL_SAT_V2_DEFAULTS,
} from "@/lib/carte/defaults";
import type {
  CapteursPlInfo,
  CapteursPlUploadResponse,
  CarteModelUploadResponse,
  ColumnDef,
  UploadResponse,
} from "@/lib/carte/types";
import {
  REQUIRED_COLUMNS,
  computeDynamicRequiredColumns,
} from "@/lib/carte/column-mapping";
import { useCarteGeneration } from "@/lib/hooks/use-carte-generation";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CartePage() {
  const router = useRouter();
  const { reset } = useAppStore();

  // Section 1 — Model uploads (folder-based)
  const [tvFolderName, setTvFolderName] = useState<string | null>(null);
  const [plFolderName, setPlFolderName] = useState<string | null>(null);
  const [tvUploading, setTvUploading] = useState(false);
  const [plUploading, setPlUploading] = useState(false);
  const [modelTvDir, setModelTvDir] = useState("");
  const [modelPlDir, setModelPlDir] = useState("");
  const [tvValid, setTvValid] = useState<boolean | null>(null);
  const [plValid, setPlValid] = useState<boolean | null>(null);
  const [tvMissing, setTvMissing] = useState<string[]>([]);
  const [plMissing, setPlMissing] = useState<string[]>([]);
  const [tvModelInfo, setTvModelInfo] = useState<CarteModelUploadResponse | null>(null);
  const [plModelInfo, setPlModelInfo] = useState<CarteModelUploadResponse | null>(null);

  // Section 1bis — Optional HPM / HPS uploads (independent, optional)
  const [hpmFolderName, setHpmFolderName] = useState<string | null>(null);
  const [hpsFolderName, setHpsFolderName] = useState<string | null>(null);
  const [hpmUploading, setHpmUploading] = useState(false);
  const [hpsUploading, setHpsUploading] = useState(false);
  const [modelHpmDir, setModelHpmDir] = useState("");
  const [modelHpsDir, setModelHpsDir] = useState("");
  const [hpmValid, setHpmValid] = useState<boolean | null>(null);
  const [hpsValid, setHpsValid] = useState<boolean | null>(null);
  const [hpmMissing, setHpmMissing] = useState<string[]>([]);
  const [hpsMissing, setHpsMissing] = useState<string[]>([]);
  const [hpmModelInfo, setHpmModelInfo] = useState<CarteModelUploadResponse | null>(null);
  const [hpsModelInfo, setHpsModelInfo] = useState<CarteModelUploadResponse | null>(null);

  // Section 2 — FCD data
  const [fcdFile, setFcdFile] = useState<File | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [rowCount, setRowCount] = useState<number>(0);
  const [columnMapping, setColumnMapping] = useState<Record<string, string | null>>({});
  const [uploading, setUploading] = useState(false);

  // Section 3 — Filters
  const [filterTvrEnabled, setFilterTvrEnabled] = useState(true);
  const [filterTvrValue, setFilterTvrValue] = useState(100);
  const [filterFcEnabled, setFilterFcEnabled] = useState(true);
  const [err01000, setErr01000] = useState(25);
  const [err10002000, setErr10002000] = useState(18);
  const [err20004000, setErr20004000] = useState(18);
  const [err4000plus, setErr4000plus] = useState(14);
  // v/h tranches IC heures de pointe (used only when HPM and/or HPS loaded).
  // D2: 0-100=25%, 100-300=18%, 300-600=18%, >600=14%. PM and PS thresholds
  // are kept independent so the user can tune HPM and HPS separately.
  const [errPm0100, setErrPm0100] = useState(25);
  const [errPm100300, setErrPm100300] = useState(18);
  const [errPm300600, setErrPm300600] = useState(18);
  const [errPm600plus, setErrPm600plus] = useState(14);
  const [errPs0100, setErrPs0100] = useState(25);
  const [errPs100300, setErrPs100300] = useState(18);
  const [errPs300600, setErrPs300600] = useState(18);
  const [errPs600plus, setErrPs600plus] = useState(14);

  // Section 3bis — Saturation hierarchique PL v3
  const [plSatEnabled, setPlSatEnabled] = useState(true);
  // BORNES_FC_ABS
  const [bornesFc1, setBornesFc1] = useState<number>(PL_SAT_BORNES_DEFAULTS.fc1);
  const [bornesFc2, setBornesFc2] = useState<number>(PL_SAT_BORNES_DEFAULTS.fc2);
  const [bornesFc3, setBornesFc3] = useState<number>(PL_SAT_BORNES_DEFAULTS.fc3);
  const [bornesFc4, setBornesFc4] = useState<number>(PL_SAT_BORNES_DEFAULTS.fc4);
  const [bornesFc5, setBornesFc5] = useState<number>(PL_SAT_BORNES_DEFAULTS.fc5);
  // ALPHA_FC_MIN
  const [alphaFc1, setAlphaFc1] = useState<number>(PL_SAT_ALPHA_DEFAULTS.fc1);
  const [alphaFc2, setAlphaFc2] = useState<number>(PL_SAT_ALPHA_DEFAULTS.fc2);
  const [alphaFc3, setAlphaFc3] = useState<number>(PL_SAT_ALPHA_DEFAULTS.fc3);
  const [alphaFc4, setAlphaFc4] = useState<number>(PL_SAT_ALPHA_DEFAULTS.fc4);
  const [alphaFc5, setAlphaFc5] = useState<number>(PL_SAT_ALPHA_DEFAULTS.fc5);
  // Hyperparamètres v2
  const [ratioMacroPen, setRatioMacroPen] = useState<number>(PL_SAT_V2_DEFAULTS.ratioMacroPen);
  const [alphaPhysiqueMax, setAlphaPhysiqueMax] = useState<number>(PL_SAT_V2_DEFAULTS.alphaPhysiqueMax);
  const [seuilVolFcdTv, setSeuilVolFcdTv] = useState<number>(PL_SAT_V2_DEFAULTS.seuilVolFcdTv);

  // === v3 zones critiques (override capteurs SIREDO PL) ===
  const [zoneCritEnabled, setZoneCritEnabled] = useState(true);
  const [capteursPlSessionId, setCapteursPlSessionId] = useState<string | null>(null);
  const [capteursPlName, setCapteursPlName] = useState<string | null>(null);
  const [capteursPlInfo, setCapteursPlInfo] = useState<CapteursPlInfo | null>(null);
  const [capteursPlUploading, setCapteursPlUploading] = useState(false);
  const [anneeCapteurs, setAnneeCapteurs] = useState(2025);
  const [ratioCapteurCritique, setRatioCapteurCritique] = useState(15);
  const [bufferZoneCritiqueM, setBufferZoneCritiqueM] = useState(1000);
  const [alphaMinZoneCritique, setAlphaMinZoneCritique] = useState(30);

  // Section 3ter — Saturation hierarchique HPM
  const [hpmSatEnabled, setHpmSatEnabled] = useState(true);
  const [borneHpmFc1, setBorneHpmFc1] = useState<number>(HPM_SAT_BORNES_DEFAULTS.fc1);
  const [borneHpmFc2, setBorneHpmFc2] = useState<number>(HPM_SAT_BORNES_DEFAULTS.fc2);
  const [borneHpmFc3, setBorneHpmFc3] = useState<number>(HPM_SAT_BORNES_DEFAULTS.fc3);
  const [borneHpmFc4, setBorneHpmFc4] = useState<number>(HPM_SAT_BORNES_DEFAULTS.fc4);
  const [borneHpmFc5, setBorneHpmFc5] = useState<number>(HPM_SAT_BORNES_DEFAULTS.fc5);
  const [alphaHpmFc1, setAlphaHpmFc1] = useState<number>(HPM_SAT_ALPHA_DEFAULTS.fc1);
  const [alphaHpmFc2, setAlphaHpmFc2] = useState<number>(HPM_SAT_ALPHA_DEFAULTS.fc2);
  const [alphaHpmFc3, setAlphaHpmFc3] = useState<number>(HPM_SAT_ALPHA_DEFAULTS.fc3);
  const [alphaHpmFc4, setAlphaHpmFc4] = useState<number>(HPM_SAT_ALPHA_DEFAULTS.fc4);
  const [alphaHpmFc5, setAlphaHpmFc5] = useState<number>(HPM_SAT_ALPHA_DEFAULTS.fc5);

  // Section 3quater — Saturation hierarchique HPS
  const [hpsSatEnabled, setHpsSatEnabled] = useState(true);
  const [borneHpsFc1, setBorneHpsFc1] = useState<number>(HPS_SAT_BORNES_DEFAULTS.fc1);
  const [borneHpsFc2, setBorneHpsFc2] = useState<number>(HPS_SAT_BORNES_DEFAULTS.fc2);
  const [borneHpsFc3, setBorneHpsFc3] = useState<number>(HPS_SAT_BORNES_DEFAULTS.fc3);
  const [borneHpsFc4, setBorneHpsFc4] = useState<number>(HPS_SAT_BORNES_DEFAULTS.fc4);
  const [borneHpsFc5, setBorneHpsFc5] = useState<number>(HPS_SAT_BORNES_DEFAULTS.fc5);
  const [alphaHpsFc1, setAlphaHpsFc1] = useState<number>(HPS_SAT_ALPHA_DEFAULTS.fc1);
  const [alphaHpsFc2, setAlphaHpsFc2] = useState<number>(HPS_SAT_ALPHA_DEFAULTS.fc2);
  const [alphaHpsFc3, setAlphaHpsFc3] = useState<number>(HPS_SAT_ALPHA_DEFAULTS.fc3);
  const [alphaHpsFc4, setAlphaHpsFc4] = useState<number>(HPS_SAT_ALPHA_DEFAULTS.fc4);
  const [alphaHpsFc5, setAlphaHpsFc5] = useState<number>(HPS_SAT_ALPHA_DEFAULTS.fc5);

  // Section 3quinquies — Arrondi progressif
  const [arrondiEnabled, setArrondiEnabled] = useState(true);

  // ---- v3 zones critiques : upload capteurs SIREDO PL ----
  // Endpoint backend : POST /api/carte/upload-capteurs-pl (FormData session_id + file)
  // Reponse : { session_id, n_capteurs, annees_disponibles, path }
  // Si absent => fallback silencieux v2 (pas de zones critiques detectees).
  const handleCapteursPlUpload = useCallback(
    async (file: File) => {
      if (!sessionId) {
        toast.error("Charge d'abord les donnees FCD (Etape 1) pour avoir une session active.");
        return;
      }
      setCapteursPlUploading(true);
      try {
        const form = new FormData();
        form.append("session_id", sessionId);
        form.append("file", file);
        const data = await apiClient.postForm<CapteursPlUploadResponse>(
          "/api/carte/upload-capteurs-pl",
          form,
          { timeoutMs: 5 * 60_000 },
        );

        setCapteursPlSessionId(data.session_id);
        setCapteursPlName(file.name);
        setCapteursPlInfo({
          n_capteurs: data.n_capteurs,
          annees_disponibles: data.annees_disponibles ?? [],
        });
        // Auto-selectionner l'annee la plus recente si dispo
        if (data.annees_disponibles && data.annees_disponibles.length > 0) {
          const maxAnnee = Math.max(...data.annees_disponibles);
          setAnneeCapteurs(maxAnnee);
        }
        toast.success(
          `${data.n_capteurs} capteurs SIREDO charges (annees : ${(data.annees_disponibles ?? []).join(", ")})`,
        );
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Erreur inconnue";
        toast.error(`Upload capteurs SIREDO echoue : ${message}`);
      } finally {
        setCapteursPlUploading(false);
      }
    },
    [sessionId],
  );

  const clearCapteursPl = useCallback(() => {
    setCapteursPlSessionId(null);
    setCapteursPlName(null);
    setCapteursPlInfo(null);
  }, []);

  // ---- FCD file upload ----
  const handleFcdUpload = useCallback(async (file: File) => {
    setFcdFile(file);
    setUploading(true);
    try {
      const res = (await uploadFile("/api/upload", file, { mode: "TV" })) as UploadResponse;
      setSessionId(res.session_id);
      setSourceColumns(res.columns.filter((c) => c !== "geometry" && c !== "__geometry_json"));
      setRowCount(res.rows);

      // Auto-map columns where names match. The remaining (model-specific)
      // targets will be filled by the auto-map effect once both models have
      // been uploaded and dynamicRequiredColumns has been computed.
      const autoMapping: Record<string, string | null> = {};
      for (const col of REQUIRED_COLUMNS) {
        const match = res.columns.find((c) => c === col.key);
        autoMapping[col.key] = match ?? null;
      }
      setColumnMapping(autoMapping);
      toast.success(`${res.rows} troncons charges depuis ${res.filename}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Erreur upload : ${message}`);
      setFcdFile(null);
    } finally {
      setUploading(false);
    }
  }, []);

  // ---- Mapping update ----
  const updateMapping = useCallback((key: string, value: string | null) => {
    setColumnMapping((prev) => ({ ...prev, [key]: value }));
  }, []);

  // ---- Dynamic required columns ----
  // Build the mapping form from the union of input_cols declared by the TV
  // and PL training_config files. Fall back to the legacy hardcoded list when
  // EITHER training_config is missing (back-compat with old models). La
  // logique pure est dans @/lib/carte/column-mapping.
  const dynamicRequiredColumns = useMemo<ColumnDef[]>(
    () =>
      computeDynamicRequiredColumns({
        tvCfg: tvModelInfo?.training_config ?? null,
        plCfg: plModelInfo?.training_config ?? null,
        hpmCfg: hpmModelInfo?.training_config ?? null,
        hpsCfg: hpsModelInfo?.training_config ?? null,
        hpmValid,
        hpsValid,
      }),
    [tvModelInfo, plModelInfo, hpmModelInfo, hpsModelInfo, hpmValid, hpsValid],
  );

  // Auto-populate the mapping with exact-name matches whenever the required
  // target list or the source column list changes. Existing user choices are
  // preserved (we only fill blanks).
  useEffect(() => {
    if (sourceColumns.length === 0) return;
    setColumnMapping((prev) => {
      const next: Record<string, string | null> = { ...prev };
      let changed = false;
      for (const col of dynamicRequiredColumns) {
        if (next[col.key] !== undefined && next[col.key] !== null && next[col.key] !== "") continue;
        const match = sourceColumns.find((c) => c === col.key);
        if (match) {
          next[col.key] = match;
          changed = true;
        } else if (next[col.key] === undefined) {
          next[col.key] = null;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [dynamicRequiredColumns, sourceColumns]);

  // ---- Progress / validation ----
  const requiredTargets = useMemo(
    () => dynamicRequiredColumns.filter((c) => c.required),
    [dynamicRequiredColumns],
  );
  const mappedRequiredCount = requiredTargets.filter(
    (c) => columnMapping[c.key] && columnMapping[c.key] !== "",
  ).length;
  const requiredMapped = requiredTargets.length > 0 && mappedRequiredCount === requiredTargets.length;
  const canGenerate = tvValid === true && plValid === true && sessionId !== null && requiredMapped;

  // ---- PL saturation : reset + helpers ----
  const resetPlSaturationDefaults = useCallback(() => {
    setBornesFc1(PL_SAT_BORNES_DEFAULTS.fc1);
    setBornesFc2(PL_SAT_BORNES_DEFAULTS.fc2);
    setBornesFc3(PL_SAT_BORNES_DEFAULTS.fc3);
    setBornesFc4(PL_SAT_BORNES_DEFAULTS.fc4);
    setBornesFc5(PL_SAT_BORNES_DEFAULTS.fc5);
    setAlphaFc1(PL_SAT_ALPHA_DEFAULTS.fc1);
    setAlphaFc2(PL_SAT_ALPHA_DEFAULTS.fc2);
    setAlphaFc3(PL_SAT_ALPHA_DEFAULTS.fc3);
    setAlphaFc4(PL_SAT_ALPHA_DEFAULTS.fc4);
    setAlphaFc5(PL_SAT_ALPHA_DEFAULTS.fc5);
    // Hyperparamètres v2 hybride adaptative
    setRatioMacroPen(PL_SAT_V2_DEFAULTS.ratioMacroPen);
    setAlphaPhysiqueMax(PL_SAT_V2_DEFAULTS.alphaPhysiqueMax);
    setSeuilVolFcdTv(PL_SAT_V2_DEFAULTS.seuilVolFcdTv);
    // v3 zones critiques (ne reset PAS l'upload capteursPlSessionId — c'est
    // une donnee user qui doit persister entre les resets)
    setZoneCritEnabled(true);
    setAnneeCapteurs(2025);
    setRatioCapteurCritique(15);
    setBufferZoneCritiqueM(1000);
    setAlphaMinZoneCritique(30);
    toast.success("Valeurs Lyon restaurees");
  }, []);

  // Detecte si l'utilisateur a modifie au moins une valeur par rapport au default
  const plSatModified = useMemo(() => {
    return (
      bornesFc1 !== PL_SAT_BORNES_DEFAULTS.fc1 ||
      bornesFc2 !== PL_SAT_BORNES_DEFAULTS.fc2 ||
      bornesFc3 !== PL_SAT_BORNES_DEFAULTS.fc3 ||
      bornesFc4 !== PL_SAT_BORNES_DEFAULTS.fc4 ||
      bornesFc5 !== PL_SAT_BORNES_DEFAULTS.fc5 ||
      alphaFc1 !== PL_SAT_ALPHA_DEFAULTS.fc1 ||
      alphaFc2 !== PL_SAT_ALPHA_DEFAULTS.fc2 ||
      alphaFc3 !== PL_SAT_ALPHA_DEFAULTS.fc3 ||
      alphaFc4 !== PL_SAT_ALPHA_DEFAULTS.fc4 ||
      alphaFc5 !== PL_SAT_ALPHA_DEFAULTS.fc5 ||
      // Hyperparamètres v2
      ratioMacroPen !== PL_SAT_V2_DEFAULTS.ratioMacroPen ||
      alphaPhysiqueMax !== PL_SAT_V2_DEFAULTS.alphaPhysiqueMax ||
      seuilVolFcdTv !== PL_SAT_V2_DEFAULTS.seuilVolFcdTv ||
      // v3 zones critiques
      zoneCritEnabled !== true ||
      anneeCapteurs !== 2025 ||
      ratioCapteurCritique !== 15 ||
      bufferZoneCritiqueM !== 1000 ||
      alphaMinZoneCritique !== 30
    );
  }, [
    bornesFc1, bornesFc2, bornesFc3, bornesFc4, bornesFc5,
    alphaFc1, alphaFc2, alphaFc3, alphaFc4, alphaFc5,
    ratioMacroPen, alphaPhysiqueMax, seuilVolFcdTv,
    zoneCritEnabled, anneeCapteurs, ratioCapteurCritique,
    bufferZoneCritiqueM, alphaMinZoneCritique,
  ]);

  // ---- HPM saturation : reset + modified detection ----
  const resetHpmSaturationDefaults = useCallback(() => {
    setBorneHpmFc1(HPM_SAT_BORNES_DEFAULTS.fc1);
    setBorneHpmFc2(HPM_SAT_BORNES_DEFAULTS.fc2);
    setBorneHpmFc3(HPM_SAT_BORNES_DEFAULTS.fc3);
    setBorneHpmFc4(HPM_SAT_BORNES_DEFAULTS.fc4);
    setBorneHpmFc5(HPM_SAT_BORNES_DEFAULTS.fc5);
    setAlphaHpmFc1(HPM_SAT_ALPHA_DEFAULTS.fc1);
    setAlphaHpmFc2(HPM_SAT_ALPHA_DEFAULTS.fc2);
    setAlphaHpmFc3(HPM_SAT_ALPHA_DEFAULTS.fc3);
    setAlphaHpmFc4(HPM_SAT_ALPHA_DEFAULTS.fc4);
    setAlphaHpmFc5(HPM_SAT_ALPHA_DEFAULTS.fc5);
    toast.success("Valeurs HPM Lyon restaurees");
  }, []);

  const hpmSatModified = useMemo(() => {
    return (
      borneHpmFc1 !== HPM_SAT_BORNES_DEFAULTS.fc1 ||
      borneHpmFc2 !== HPM_SAT_BORNES_DEFAULTS.fc2 ||
      borneHpmFc3 !== HPM_SAT_BORNES_DEFAULTS.fc3 ||
      borneHpmFc4 !== HPM_SAT_BORNES_DEFAULTS.fc4 ||
      borneHpmFc5 !== HPM_SAT_BORNES_DEFAULTS.fc5 ||
      alphaHpmFc1 !== HPM_SAT_ALPHA_DEFAULTS.fc1 ||
      alphaHpmFc2 !== HPM_SAT_ALPHA_DEFAULTS.fc2 ||
      alphaHpmFc3 !== HPM_SAT_ALPHA_DEFAULTS.fc3 ||
      alphaHpmFc4 !== HPM_SAT_ALPHA_DEFAULTS.fc4 ||
      alphaHpmFc5 !== HPM_SAT_ALPHA_DEFAULTS.fc5
    );
  }, [
    borneHpmFc1, borneHpmFc2, borneHpmFc3, borneHpmFc4, borneHpmFc5,
    alphaHpmFc1, alphaHpmFc2, alphaHpmFc3, alphaHpmFc4, alphaHpmFc5,
  ]);

  // ---- HPS saturation : reset + modified detection ----
  const resetHpsSaturationDefaults = useCallback(() => {
    setBorneHpsFc1(HPS_SAT_BORNES_DEFAULTS.fc1);
    setBorneHpsFc2(HPS_SAT_BORNES_DEFAULTS.fc2);
    setBorneHpsFc3(HPS_SAT_BORNES_DEFAULTS.fc3);
    setBorneHpsFc4(HPS_SAT_BORNES_DEFAULTS.fc4);
    setBorneHpsFc5(HPS_SAT_BORNES_DEFAULTS.fc5);
    setAlphaHpsFc1(HPS_SAT_ALPHA_DEFAULTS.fc1);
    setAlphaHpsFc2(HPS_SAT_ALPHA_DEFAULTS.fc2);
    setAlphaHpsFc3(HPS_SAT_ALPHA_DEFAULTS.fc3);
    setAlphaHpsFc4(HPS_SAT_ALPHA_DEFAULTS.fc4);
    setAlphaHpsFc5(HPS_SAT_ALPHA_DEFAULTS.fc5);
    toast.success("Valeurs HPS Lyon restaurees");
  }, []);

  const hpsSatModified = useMemo(() => {
    return (
      borneHpsFc1 !== HPS_SAT_BORNES_DEFAULTS.fc1 ||
      borneHpsFc2 !== HPS_SAT_BORNES_DEFAULTS.fc2 ||
      borneHpsFc3 !== HPS_SAT_BORNES_DEFAULTS.fc3 ||
      borneHpsFc4 !== HPS_SAT_BORNES_DEFAULTS.fc4 ||
      borneHpsFc5 !== HPS_SAT_BORNES_DEFAULTS.fc5 ||
      alphaHpsFc1 !== HPS_SAT_ALPHA_DEFAULTS.fc1 ||
      alphaHpsFc2 !== HPS_SAT_ALPHA_DEFAULTS.fc2 ||
      alphaHpsFc3 !== HPS_SAT_ALPHA_DEFAULTS.fc3 ||
      alphaHpsFc4 !== HPS_SAT_ALPHA_DEFAULTS.fc4 ||
      alphaHpsFc5 !== HPS_SAT_ALPHA_DEFAULTS.fc5
    );
  }, [
    borneHpsFc1, borneHpsFc2, borneHpsFc3, borneHpsFc4, borneHpsFc5,
    alphaHpsFc1, alphaHpsFc2, alphaHpsFc3, alphaHpsFc4, alphaHpsFc5,
  ]);

  // ---- Generation (hook isole — payload identique a l'inline d'origine) ----
  const generationModels = useMemo(
    () => ({ modelTvDir, modelPlDir, modelHpmDir, modelHpsDir }),
    [modelTvDir, modelPlDir, modelHpmDir, modelHpsDir],
  );
  const generationFilters = useMemo(
    () => ({
      filterTvrEnabled,
      filterTvrValue,
      filterFcEnabled,
      err01000,
      err10002000,
      err20004000,
      err4000plus,
      errPm0100,
      errPm100300,
      errPm300600,
      errPm600plus,
      errPs0100,
      errPs100300,
      errPs300600,
      errPs600plus,
      arrondiEnabled,
    }),
    [
      filterTvrEnabled, filterTvrValue, filterFcEnabled,
      err01000, err10002000, err20004000, err4000plus,
      errPm0100, errPm100300, errPm300600, errPm600plus,
      errPs0100, errPs100300, errPs300600, errPs600plus,
      arrondiEnabled,
    ],
  );
  const generationSaturations = useMemo(
    () => ({
      pl: {
        enabled: plSatEnabled,
        bornesFc1, bornesFc2, bornesFc3, bornesFc4, bornesFc5,
        alphaFc1, alphaFc2, alphaFc3, alphaFc4, alphaFc5,
        ratioMacroPen, alphaPhysiqueMax, seuilVolFcdTv,
        zoneCritEnabled, capteursPlSessionId, anneeCapteurs,
        ratioCapteurCritique, bufferZoneCritiqueM, alphaMinZoneCritique,
      },
      hpm: {
        enabled: hpmSatEnabled,
        borneFc1: borneHpmFc1, borneFc2: borneHpmFc2, borneFc3: borneHpmFc3,
        borneFc4: borneHpmFc4, borneFc5: borneHpmFc5,
        alphaFc1: alphaHpmFc1, alphaFc2: alphaHpmFc2, alphaFc3: alphaHpmFc3,
        alphaFc4: alphaHpmFc4, alphaFc5: alphaHpmFc5,
      },
      hps: {
        enabled: hpsSatEnabled,
        borneFc1: borneHpsFc1, borneFc2: borneHpsFc2, borneFc3: borneHpsFc3,
        borneFc4: borneHpsFc4, borneFc5: borneHpsFc5,
        alphaFc1: alphaHpsFc1, alphaFc2: alphaHpsFc2, alphaFc3: alphaHpsFc3,
        alphaFc4: alphaHpsFc4, alphaFc5: alphaHpsFc5,
      },
    }),
    [
      plSatEnabled,
      bornesFc1, bornesFc2, bornesFc3, bornesFc4, bornesFc5,
      alphaFc1, alphaFc2, alphaFc3, alphaFc4, alphaFc5,
      ratioMacroPen, alphaPhysiqueMax, seuilVolFcdTv,
      zoneCritEnabled, capteursPlSessionId, anneeCapteurs,
      ratioCapteurCritique, bufferZoneCritiqueM, alphaMinZoneCritique,
      hpmSatEnabled,
      borneHpmFc1, borneHpmFc2, borneHpmFc3, borneHpmFc4, borneHpmFc5,
      alphaHpmFc1, alphaHpmFc2, alphaHpmFc3, alphaHpmFc4, alphaHpmFc5,
      hpsSatEnabled,
      borneHpsFc1, borneHpsFc2, borneHpsFc3, borneHpsFc4, borneHpsFc5,
      alphaHpsFc1, alphaHpsFc2, alphaHpsFc3, alphaHpsFc4, alphaHpsFc5,
    ],
  );

  const {
    generate: handleGenerate,
    generating,
    progress,
    progressText,
    done,
    stats,
    resetResults,
  } = useCarteGeneration({
    sessionId,
    models: generationModels,
    mapping: columnMapping,
    filters: generationFilters,
    saturations: generationSaturations,
    canGenerate,
  });

  // ---- Download ----
  // Use apiClient.download so the Bearer token is attached when going
  // cross-origin (window.open cannot set the Authorization header).
  const handleDownload = useCallback(() => {
    if (!sessionId) return;
    apiClient
      .download(`/api/carte/download/${sessionId}`, `carte_debits_${sessionId.slice(0, 8)}.geojson`)
      .catch((err: Error) => toast.error(`Telechargement echoue : ${err.message}`));
  }, [sessionId]);

  // =========================================================================
  // RENDER
  // =========================================================================

  return (
    <div className="relative min-h-screen">
      <AuroraBg />
      <div className="relative z-10 max-w-5xl mx-auto px-4 py-8 space-y-8">
        {/* Header */}
        <div className="flex items-center gap-3">
          <NeonButton
            variant="ghost"
            onClick={() => { reset(); router.push("/"); }}
            icon={<ArrowLeft size={14} />}
            className="text-xs"
          >
            Accueil
          </NeonButton>
          <div className="px-3 py-1 rounded-lg bg-cyan/10 text-cyan text-xs font-bold uppercase tracking-wide">
            Carte de Debits
          </div>
        </div>

        <div className="space-y-2">
          <GradientText as="h1" className="text-2xl">
            Generation de la Carte des Debits
          </GradientText>
          <p className="text-sm text-slate-300">
            Appliquez les modeles TV et PL sur vos donnees FCD pour estimer les debits
            de trafic sur chaque troncon routier.
          </p>
        </div>

        {/* ============================================================= */}
        {/* SECTION 1 — Donnees FCD                                       */}
        {/* ============================================================= */}
        <FcdUploadSection
          fcdFile={fcdFile}
          uploading={uploading}
          sessionId={sessionId}
          rowCount={rowCount}
          sourceColumns={sourceColumns}
          onFcdUpload={handleFcdUpload}
          onFcdClear={() => {
            setFcdFile(null);
            setSessionId(null);
            setSourceColumns([]);
            setRowCount(0);
            setColumnMapping({});
            resetResults();
          }}
          columnMapping={columnMapping}
          updateMapping={updateMapping}
          dynamicRequiredColumns={dynamicRequiredColumns}
          mappedRequiredCount={mappedRequiredCount}
          requiredTargetsCount={requiredTargets.length}
          requiredMapped={requiredMapped}
          tvModelInfo={tvModelInfo}
          plModelInfo={plModelInfo}
        />

        {/* ============================================================= */}
        {/* SECTION 2 — Selection des modeles                              */}
        {/* ============================================================= */}
        <GlowCard glowColor="accent">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-7 h-7 rounded-lg bg-accent/20 flex items-center justify-center text-accent text-xs font-bold">2</div>
            <h3 className="text-sm font-semibold text-white">Selection des modeles</h3>
          </div>
          <p className="text-xs text-slate-400 mb-3">
            Parcourez un dossier de modele pour chaque type. Le dossier doit contenir
            NNarchitecture.json, NNweights.weights.h5 (ou NNweights.h5) et NNnormCoefficients.json.
            Les modeles <span className="text-pink-400">HPM</span> et{" "}
            <span className="text-violet-400">HPS</span> sont optionnels et permettent
            d&apos;enrichir la carte avec les debits de pointe matin / soir (v/h).
          </p>
          {!sessionId && (
            <div className="mb-5 flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs">
              <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
              <span>Importez d&apos;abord le fichier FCD (Etape 1) avant les modeles.</span>
            </div>
          )}

          <div className={`grid grid-cols-1 md:grid-cols-2 gap-6 ${!sessionId ? "opacity-50 pointer-events-none" : ""}`}>
            <ModelUploadSection
              kind="tv"
              sessionId={sessionId}
              folderName={tvFolderName}
              isUploading={tvUploading}
              valid={tvValid}
              missing={tvMissing}
              icon={<Car size={16} className="text-accent" />}
              label="Modele TV (Trafic Vehicules)"
              browseLabel="Parcourir le dossier du modele TV"
              browseDescription="Selectionnez le dossier contenant le modele"
              onUploadStart={(folder) => {
                setTvFolderName(folder);
                setTvUploading(true);
              }}
              onUploadSuccess={(data) => {
                setModelTvDir(data.model_dir);
                setTvValid(data.valid);
                setTvMissing(data.missing_files);
                setTvModelInfo(data);
              }}
              onUploadError={() => {
                setTvValid(false);
                setTvMissing(["(erreur upload)"]);
                setTvModelInfo(null);
              }}
              onUploadFinally={() => setTvUploading(false)}
              onClear={() => {
                setTvFolderName(null);
                setTvValid(null);
                setTvMissing([]);
                setModelTvDir("");
                setTvModelInfo(null);
              }}
            />

            <ModelUploadSection
              kind="pl"
              sessionId={sessionId}
              folderName={plFolderName}
              isUploading={plUploading}
              valid={plValid}
              missing={plMissing}
              icon={<Truck size={16} className="text-violet" />}
              label="Modele PL (Poids Lourds)"
              browseLabel="Parcourir le dossier du modele PL"
              browseDescription="Selectionnez le dossier contenant le modele"
              onUploadStart={(folder) => {
                setPlFolderName(folder);
                setPlUploading(true);
              }}
              onUploadSuccess={(data) => {
                setModelPlDir(data.model_dir);
                setPlValid(data.valid);
                setPlMissing(data.missing_files);
                setPlModelInfo(data);
              }}
              onUploadError={() => {
                setPlValid(false);
                setPlMissing(["(erreur upload)"]);
                setPlModelInfo(null);
              }}
              onUploadFinally={() => setPlUploading(false)}
              onClear={() => {
                setPlFolderName(null);
                setPlValid(null);
                setPlMissing([]);
                setModelPlDir("");
                setPlModelInfo(null);
              }}
            />
          </div>

          {/* --- Optional models : HPM / HPS --- */}
          <div className="mt-8 pt-6 border-t border-white/[0.06]">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold text-slate-200">Modeles heures de pointe (optionnels)</span>
              <span className="text-[10px] text-slate-400 bg-surface-light px-1.5 py-0.5 rounded">
                optionnel
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mb-4">
              Charge un ou les deux modeles pour ajouter les debits de pointe (v/h) avec
              intervalles de confiance. Chaque modele est independant et peut etre charge seul.
            </p>

            <div className={`grid grid-cols-1 md:grid-cols-2 gap-6 ${!sessionId ? "opacity-50 pointer-events-none" : ""}`}>
              <ModelUploadSection
                kind="hpm"
                sessionId={sessionId}
                folderName={hpmFolderName}
                isUploading={hpmUploading}
                valid={hpmValid}
                missing={hpmMissing}
                icon={<Sunrise size={16} className="text-pink-400" />}
                label="Modele HPM (Heure de Pointe Matin)"
                browseLabel="Parcourir le dossier du modele HPM"
                browseDescription="Optionnel - selectionnez le dossier"
                hint="Ajoute PM / PMmin / PMmax (v/h) a la carte"
                showLoadedBadge
                dimWhenEmpty
                onUploadStart={(folder) => {
                  setHpmFolderName(folder);
                  setHpmUploading(true);
                }}
                onUploadSuccess={(data) => {
                  setModelHpmDir(data.model_dir);
                  setHpmValid(data.valid);
                  setHpmMissing(data.missing_files);
                  setHpmModelInfo(data);
                }}
                onUploadError={() => {
                  setHpmValid(false);
                  setHpmMissing(["(erreur upload)"]);
                  setHpmModelInfo(null);
                }}
                onUploadFinally={() => setHpmUploading(false)}
                onClear={() => {
                  setHpmFolderName(null);
                  setHpmValid(null);
                  setHpmMissing([]);
                  setModelHpmDir("");
                  setHpmModelInfo(null);
                }}
              />

              <ModelUploadSection
                kind="hps"
                sessionId={sessionId}
                folderName={hpsFolderName}
                isUploading={hpsUploading}
                valid={hpsValid}
                missing={hpsMissing}
                icon={<Sunset size={16} className="text-violet-400" />}
                label="Modele HPS (Heure de Pointe Soir)"
                browseLabel="Parcourir le dossier du modele HPS"
                browseDescription="Optionnel - selectionnez le dossier"
                hint="Ajoute PS / PSmin / PSmax (v/h) a la carte"
                showLoadedBadge
                dimWhenEmpty
                onUploadStart={(folder) => {
                  setHpsFolderName(folder);
                  setHpsUploading(true);
                }}
                onUploadSuccess={(data) => {
                  setModelHpsDir(data.model_dir);
                  setHpsValid(data.valid);
                  setHpsMissing(data.missing_files);
                  setHpsModelInfo(data);
                }}
                onUploadError={() => {
                  setHpsValid(false);
                  setHpsMissing(["(erreur upload)"]);
                  setHpsModelInfo(null);
                }}
                onUploadFinally={() => setHpsUploading(false)}
                onClear={() => {
                  setHpsFolderName(null);
                  setHpsValid(null);
                  setHpsMissing([]);
                  setModelHpsDir("");
                  setHpsModelInfo(null);
                }}
              />
            </div>
          </div>
        </GlowCard>

        {/* ============================================================= */}
        {/* SECTION 3 — Filtres et parametres                              */}
        {/* ============================================================= */}
        <GlowCard glowColor="violet">
          <div className="flex items-center gap-2 mb-5">
            <div className="w-7 h-7 rounded-lg bg-violet/20 flex items-center justify-center text-violet text-xs font-bold">3</div>
            <h3 className="text-sm font-semibold text-white">Filtres et parametres</h3>
          </div>

          <FiltersSection
            filterTvrEnabled={filterTvrEnabled}
            setFilterTvrEnabled={setFilterTvrEnabled}
            filterTvrValue={filterTvrValue}
            setFilterTvrValue={setFilterTvrValue}
            filterFcEnabled={filterFcEnabled}
            setFilterFcEnabled={setFilterFcEnabled}
            err01000={err01000}
            setErr01000={setErr01000}
            err10002000={err10002000}
            setErr10002000={setErr10002000}
            err20004000={err20004000}
            setErr20004000={setErr20004000}
            err4000plus={err4000plus}
            setErr4000plus={setErr4000plus}
            hpmValid={hpmValid}
            errPm0100={errPm0100}
            setErrPm0100={setErrPm0100}
            errPm100300={errPm100300}
            setErrPm100300={setErrPm100300}
            errPm300600={errPm300600}
            setErrPm300600={setErrPm300600}
            errPm600plus={errPm600plus}
            setErrPm600plus={setErrPm600plus}
            hpsValid={hpsValid}
            errPs0100={errPs0100}
            setErrPs0100={setErrPs0100}
            errPs100300={errPs100300}
            setErrPs100300={setErrPs100300}
            errPs300600={errPs300600}
            setErrPs300600={setErrPs300600}
            errPs600plus={errPs600plus}
            setErrPs600plus={setErrPs600plus}
          />

          <PlSaturationPanel
            plSatEnabled={plSatEnabled}
            onPlSatEnabledChange={setPlSatEnabled}
            bornesFc1={bornesFc1}
            bornesFc2={bornesFc2}
            bornesFc3={bornesFc3}
            bornesFc4={bornesFc4}
            bornesFc5={bornesFc5}
            onBornesFc1Change={setBornesFc1}
            onBornesFc2Change={setBornesFc2}
            onBornesFc3Change={setBornesFc3}
            onBornesFc4Change={setBornesFc4}
            onBornesFc5Change={setBornesFc5}
            alphaFc1={alphaFc1}
            alphaFc2={alphaFc2}
            alphaFc3={alphaFc3}
            alphaFc4={alphaFc4}
            alphaFc5={alphaFc5}
            onAlphaFc1Change={setAlphaFc1}
            onAlphaFc2Change={setAlphaFc2}
            onAlphaFc3Change={setAlphaFc3}
            onAlphaFc4Change={setAlphaFc4}
            onAlphaFc5Change={setAlphaFc5}
            ratioMacroPen={ratioMacroPen}
            alphaPhysiqueMax={alphaPhysiqueMax}
            seuilVolFcdTv={seuilVolFcdTv}
            onRatioMacroPenChange={setRatioMacroPen}
            onAlphaPhysiqueMaxChange={setAlphaPhysiqueMax}
            onSeuilVolFcdTvChange={setSeuilVolFcdTv}
            zoneCritEnabled={zoneCritEnabled}
            onZoneCritEnabledChange={setZoneCritEnabled}
            capteursPlSessionId={capteursPlSessionId}
            capteursPlName={capteursPlName}
            capteursPlInfo={capteursPlInfo}
            capteursPlUploading={capteursPlUploading}
            onCapteursPlUpload={handleCapteursPlUpload}
            onCapteursPlClear={clearCapteursPl}
            anneeCapteurs={anneeCapteurs}
            onAnneeCapteursChange={setAnneeCapteurs}
            ratioCapteurCritique={ratioCapteurCritique}
            onRatioCapteurCritiqueChange={setRatioCapteurCritique}
            bufferZoneCritiqueM={bufferZoneCritiqueM}
            onBufferZoneCritiqueMChange={setBufferZoneCritiqueM}
            alphaMinZoneCritique={alphaMinZoneCritique}
            onAlphaMinZoneCritiqueChange={setAlphaMinZoneCritique}
            plSatModified={plSatModified}
            onReset={resetPlSaturationDefaults}
          />

          <AnimatePresence>
            <HourlySaturationPanel
              mode="hpm"
              visible={hpmValid === true}
              enabled={hpmSatEnabled}
              modified={hpmSatModified}
              onEnabledChange={setHpmSatEnabled}
              borneFc1={borneHpmFc1}
              borneFc2={borneHpmFc2}
              borneFc3={borneHpmFc3}
              borneFc4={borneHpmFc4}
              borneFc5={borneHpmFc5}
              onBorneFc1Change={setBorneHpmFc1}
              onBorneFc2Change={setBorneHpmFc2}
              onBorneFc3Change={setBorneHpmFc3}
              onBorneFc4Change={setBorneHpmFc4}
              onBorneFc5Change={setBorneHpmFc5}
              alphaFc1={alphaHpmFc1}
              alphaFc2={alphaHpmFc2}
              alphaFc3={alphaHpmFc3}
              alphaFc4={alphaHpmFc4}
              alphaFc5={alphaHpmFc5}
              onAlphaFc1Change={setAlphaHpmFc1}
              onAlphaFc2Change={setAlphaHpmFc2}
              onAlphaFc3Change={setAlphaHpmFc3}
              onAlphaFc4Change={setAlphaHpmFc4}
              onAlphaFc5Change={setAlphaHpmFc5}
              onReset={resetHpmSaturationDefaults}
            />
          </AnimatePresence>

          <AnimatePresence>
            <HourlySaturationPanel
              mode="hps"
              visible={hpsValid === true}
              enabled={hpsSatEnabled}
              modified={hpsSatModified}
              onEnabledChange={setHpsSatEnabled}
              borneFc1={borneHpsFc1}
              borneFc2={borneHpsFc2}
              borneFc3={borneHpsFc3}
              borneFc4={borneHpsFc4}
              borneFc5={borneHpsFc5}
              onBorneFc1Change={setBorneHpsFc1}
              onBorneFc2Change={setBorneHpsFc2}
              onBorneFc3Change={setBorneHpsFc3}
              onBorneFc4Change={setBorneHpsFc4}
              onBorneFc5Change={setBorneHpsFc5}
              alphaFc1={alphaHpsFc1}
              alphaFc2={alphaHpsFc2}
              alphaFc3={alphaHpsFc3}
              alphaFc4={alphaHpsFc4}
              alphaFc5={alphaHpsFc5}
              onAlphaFc1Change={setAlphaHpsFc1}
              onAlphaFc2Change={setAlphaHpsFc2}
              onAlphaFc3Change={setAlphaHpsFc3}
              onAlphaFc4Change={setAlphaHpsFc4}
              onAlphaFc5Change={setAlphaHpsFc5}
              onReset={resetHpsSaturationDefaults}
            />
          </AnimatePresence>

          <ArrondiToggleCard
            arrondiEnabled={arrondiEnabled}
            setArrondiEnabled={setArrondiEnabled}
          />
        </GlowCard>

        {/* ============================================================= */}
        {/* SECTION 4 — Generation                                         */}
        {/* ============================================================= */}
        <GenerationSection
          canGenerate={canGenerate}
          generating={generating}
          done={done}
          progress={progress}
          progressText={progressText}
          onGenerate={handleGenerate}
          tvValid={tvValid}
          plValid={plValid}
          sessionId={sessionId}
          requiredMapped={requiredMapped}
        />

        {/* ============================================================= */}
        {/* RESULTS — UX5 : NeonBorder success + ShimmerText + StatBadges */}
        {/* + MagneticButton. La logique (stats, sessionId, download) est */}
        {/* identique a la version originale.                              */}
        {/* ============================================================= */}
        <AnimatePresence>
          {done && stats && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <NeonBorder tone="success" speed={3.2} className="overflow-hidden">
                <div className="text-center px-6 py-7 space-y-5">
                  <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto">
                    <Map size={28} />
                  </div>

                  <ShimmerText
                    as="h3"
                    variant="cyan"
                    className="text-base font-semibold"
                  >
                    Carte generee avec succes
                  </ShimmerText>

                  <RevealOnScroll
                    variant="scale"
                    stagger={0.06}
                    className="flex flex-wrap items-center justify-center gap-2 max-w-3xl mx-auto"
                  >
                    <StatBadge
                      tone="accent"
                      icon={<Layers />}
                      label="troncons totaux"
                      value={stats.total_segments.toLocaleString("fr-FR")}
                    />
                    <StatBadge
                      tone="violet"
                      icon={<Filter />}
                      label="troncons filtres"
                      value={stats.filtered_segments.toLocaleString("fr-FR")}
                    />
                    <StatBadge
                      tone="cyan"
                      icon={<Car />}
                      label="JOr moyen veh/j"
                      value={
                        stats.mean_tvr != null
                          ? Math.round(stats.mean_tvr).toLocaleString("fr-FR")
                          : "-"
                      }
                    />
                    <StatBadge
                      tone="amber"
                      icon={<Truck />}
                      label="DPL moyen PL/j"
                      value={
                        stats.mean_dpl != null
                          ? Math.round(stats.mean_dpl).toLocaleString("fr-FR")
                          : "-"
                      }
                    />
                  </RevealOnScroll>

                  <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
                    <MagneticButton
                      variant="primary"
                      size="lg"
                      onClick={() =>
                        sessionId && router.push(`/carte/visualiser/${sessionId}`)
                      }
                      disabled={!sessionId}
                    >
                      <Map size={16} />
                      Visualiser sur la carte
                    </MagneticButton>
                    <MagneticButton
                      variant="secondary"
                      size="lg"
                      onClick={handleDownload}
                    >
                      <Download size={16} />
                      Telecharger le GeoJSON
                    </MagneticButton>
                  </div>
                </div>
              </NeonBorder>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
