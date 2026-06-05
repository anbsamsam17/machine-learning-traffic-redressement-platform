"use client";

/**
 * Module "Carte d'evolution des debits" — UX unifie (refonte 2026-06,
 * calquee sur /discontinuites).
 *
 * Une SEULE carte MapLibre (via <MapView />) TOUJOURS visible, inline :
 *  - Phases idle/upload/generating : affiche une PREVISUALISATION (dataset
 *    d'exemple `/preview/evolution-lyon.geojson`) coloree par dJOr (palette
 *    divergente bleu<->orange). Interactions data desactivees (badge "Apercu").
 *  - Phase ready (status done) : CROSSFADE GSAP de la prevues vers la VRAIE
 *    carte (`/api/evolution/result/{sid}`), interactions activees (popups
 *    dJOr/JOr%/T1/T2/match/sig), legende interactive (EvolutionLegend) +
 *    bouton Telecharger. UNE SEULE instance de carte.
 *
 * Le crossfade respecte `prefers-reduced-motion` (swap instantane si reduit).
 *
 * Endpoints backend consommes :
 *  - POST /api/evolution/upload   (multipart: file_t1, file_t2) -> {session_id}
 *  - POST /api/evolution/generate {session_id, use_ban, plancher_t1,
 *                                  include_new} -> background
 *  - GET  /api/evolution/status/{sid} -> {stage, progress, done, error, stats}
 *  - GET  /api/evolution/result/{sid} -> GeoJSON reel (LineString FC)
 *  - GET  /api/evolution/download/{sid} (Bearer)
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  Crosshair,
  Download,
  Eye,
  Filter as FilterIcon,
  GitCompareArrows,
  Layers,
  Loader2,
  RotateCcw,
  Search,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";
import type {
  Feature,
  FeatureCollection,
  GeoJsonProperties,
  LineString,
} from "geojson";
import maplibregl from "maplibre-gl";
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";

import { MapView, type MapViewPaintOverrides } from "@/components/map/MapView";
import { EvolutionLegend } from "@/components/map/EvolutionLegend";
import {
  buildEvolutionColorExpression,
  buildEvolutionLineWidthExpression,
  buildEvolutionOpacityExpression,
  buildEvolutionFilter,
  bucketIndexOf,
  DEFAULT_THRESHOLDS,
} from "@/lib/evolution-palette";
import { DropZone } from "@/components/upload/drop-zone";
import { NeonButton } from "@/components/ui/neon-button";
import {
  MagneticButton,
  NeonBorder,
  ShimmerText,
} from "@/components/ui";
import { apiClient } from "@/lib/api";
import { getApiBase } from "@/lib/api-url";
import { getToken } from "@/lib/auth";

// ---------------------------------------------------------------------------
// Types — contrat backend /api/evolution/*
// ---------------------------------------------------------------------------

interface UploadResponse {
  session_id: string;
}

interface GenerateResponse {
  session_id: string;
  started: boolean;
}

/** Statistiques agregees renvoyees par /status une fois done=true. */
interface EvolutionStats {
  n_total?: number;
  n_cle?: number;
  n_geom_auto?: number;
  n_geom_verif?: number;
  n_non_match?: number;
  n_sig?: number;
  jor_min?: number;
  jor_median?: number;
  jor_max?: number;
}

interface StatusResponse {
  stage: string;
  progress: number; // 0..100
  done: boolean;
  error: string | null;
  stats: EvolutionStats | null;
}

type SegmentFeature = Feature<LineString, GeoJsonProperties>;
type SegmentCollection = FeatureCollection<LineString, GeoJsonProperties>;

interface EvolutionKpis {
  total: number;
  hausses: number; // dJOr > 0
  baisses: number; // dJOr < 0
  significatifs: number; // sig === 1
  medianJor: number | null; // mediane des JOr non null (%)
}

const ACCEPT_GEOJSON: Record<string, string[]> = {
  "application/json": [".geojson", ".json"],
  "application/geo+json": [".geojson"],
};

const POLL_INTERVAL_MS = 1500;
const NF_FR = new Intl.NumberFormat("fr-FR");
const PREVIEW_URL = "/preview/evolution-lyon.geojson";

// MapView gere sa propre couche : ces IDs sont ceux installes en interne.
const REAL_LAYER_ID = "carte-segments-line";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)} %`;
}

function computeKpis(features: SegmentFeature[]): EvolutionKpis {
  let hausses = 0;
  let baisses = 0;
  let significatifs = 0;
  const jors: number[] = [];

  for (const f of features) {
    const props = f.properties ?? {};
    const jorRaw = props.JOr;
    const jor = jorRaw == null ? null : Number(jorRaw);
    if (jor != null && isFinite(jor)) {
      jors.push(jor);
      if (jor > 0) hausses += 1;
      else if (jor < 0) baisses += 1;
    }
    if (Number(props.sig ?? 0) === 1) significatifs += 1;
  }

  return {
    total: features.length,
    hausses,
    baisses,
    significatifs,
    medianJor: median(jors),
  };
}

function featureCentroid(f: SegmentFeature): [number, number] | null {
  const coords = f.geometry?.coordinates;
  if (!coords || coords.length === 0) return null;
  const mid = coords[Math.floor(coords.length / 2)];
  if (!mid || mid.length < 2) return null;
  return [mid[0], mid[1]];
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false)
  );
}

// ---------------------------------------------------------------------------
// Popup HTML — dJOr (veh/j, primaire) / JOr% / T1 / T2 / match / sig
// ---------------------------------------------------------------------------

function renderEvolutionPopup(raw: GeoJsonProperties): string {
  const p = (raw ?? {}) as Record<string, unknown>;
  const mono = "ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace";

  const row = (label: string, value: string, valueColor = "#f8fafc") =>
    `<div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span style="color:#94a3b8;font-size:11px">${label}</span><span style="color:${valueColor};font-size:12px;font-family:${mono};font-variant-numeric:tabular-nums">${value}</span></div>`;

  const num = (v: unknown, unit = ""): string => {
    if (v == null) return "—";
    const n = Number(v);
    if (!isFinite(n)) return "—";
    const out = NF_FR.format(Math.round(n));
    return unit ? `${out} ${unit}` : out;
  };

  // dJOr : variation ABSOLUE en veh/j (metrique primaire de la carte).
  const djorRaw = p.dJOr;
  const djorN = djorRaw == null ? null : Number(djorRaw);
  const djorStr =
    djorN == null || !isFinite(djorN)
      ? "—"
      : `${djorN > 0 ? "+" : ""}${NF_FR.format(Math.round(djorN))} véh/j`;
  // Bleu = baisse, orange = hausse (coherent avec la rampe divergente).
  const djorColor =
    djorN == null || !isFinite(djorN)
      ? "#cbd5e1"
      : djorN > 0
        ? "#fdae6b"
        : djorN < 0
          ? "#9ecae1"
          : "#fde68a";

  // JOr : pourcentage (secondaire).
  const jorRaw = p.JOr;
  const jorN = jorRaw == null ? null : Number(jorRaw);
  const jorStr =
    jorN == null || !isFinite(jorN)
      ? "—"
      : `${jorN > 0 ? "+" : ""}${jorN.toFixed(2)} %`;

  const sig = Number(p.sig ?? 0) === 1;
  const sigBadge = `<span style="display:inline-block;padding:1px 7px;border-radius:9px;font-size:10px;font-weight:600;${
    sig
      ? "background:rgba(16,185,129,.18);color:#6ee7b7"
      : "background:rgba(148,163,184,.18);color:#cbd5e1"
  }">${sig ? "significatif" : "non significatif"}</span>`;

  const matchLevel = p.match_level != null ? String(p.match_level) : "—";
  const matchScore =
    p.match_score == null || !isFinite(Number(p.match_score))
      ? null
      : Number(p.match_score).toFixed(3);

  return `
    <div style="font-family:Inter,system-ui,sans-serif;color:#f8fafc;min-width:248px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,.1)">
        <span style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em">Troncon</span>
        <span style="font-size:11px;font-family:${mono};color:#a5b4fc">#${p.agregId ?? "—"}</span>
      </div>
      <div style="display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding:4px 0 8px;border-bottom:1px solid rgba(255,255,255,.1);margin-bottom:6px">
        <span style="color:#94a3b8;font-size:11px">Évolution TMJO (dJOr)</span>
        <span style="color:${djorColor};font-size:16px;font-weight:600;font-family:${mono};font-variant-numeric:tabular-nums">${djorStr}</span>
      </div>
      ${row("Évolution JOr (%)", jorStr)}
      ${row("T1 (année 1)", num(p.T1, "véh/j"))}
      ${row("T2 (année 2)", num(p.T2, "véh/j"))}
      ${row("Appariement", matchScore ? `${matchLevel} (${matchScore})` : matchLevel)}
      <div style="display:flex;justify-content:space-between;gap:12px;padding-top:6px"><span style="color:#94a3b8;font-size:11px">Statut</span>${sigBadge}</div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// KPI card
// ---------------------------------------------------------------------------

function KpiCard({
  label,
  value,
  icon,
  hint,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="surface-elevated p-3 flex items-start gap-3">
      <div className="shrink-0 w-8 h-8 rounded bg-accent-subtle flex items-center justify-center text-accent [&_svg]:size-4">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-wide text-text-muted truncate">
          {label}
        </p>
        <p className="font-mono text-lg font-semibold mt-0.5 tabular-nums leading-none text-text truncate">
          {value}
        </p>
        {hint && (
          <p className="text-[10px] text-text-subtle mt-1 truncate">{hint}</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Machine d'etats
// ---------------------------------------------------------------------------

type Phase = "upload" | "generating" | "ready";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function EvolutionPage() {
  const router = useRouter();

  // --- Hydration gate ----------------------------------------------------
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
  }, []);

  // --- Machine d'etats ---------------------------------------------------
  const [phase, setPhase] = useState<Phase>("upload");

  // --- Uploads -----------------------------------------------------------
  const [fileT1, setFileT1] = useState<File | null>(null);
  const [fileT2, setFileT2] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // --- Options -----------------------------------------------------------
  const [useBan, setUseBan] = useState(true);
  const [plancherT1, setPlancherT1] = useState(50);
  const [includeNew, setIncludeNew] = useState(false);

  // --- Generation / polling ---------------------------------------------
  const [generating, setGenerating] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [progress, setProgress] = useState(0);

  // --- Datasets : preview (exemple) + real (resultat) -------------------
  const [previewGeojson, setPreviewGeojson] =
    useState<SegmentCollection | null>(null);
  const [realGeojson, setRealGeojson] = useState<SegmentCollection | null>(null);
  const [resultLoading, setResultLoading] = useState(false);
  const [resultProgress, setResultProgress] = useState(0);

  // GeoJSON ACTIF affiche par la carte (preview tant que pas ready/real).
  const activeGeojson = realGeojson ?? previewGeojson;
  const showingReal = realGeojson != null;

  // --- Legend-driven state (COMPASS) ------------------------------------
  const [thresholds, setThresholds] = useState<number[]>([
    ...DEFAULT_THRESHOLDS,
  ]);
  const [visibleBuckets, setVisibleBuckets] = useState<Set<number>>(
    () => new Set([0, 1, 2, 3]),
  );
  const [showNeutral, setShowNeutral] = useState(true);
  const [layerVisible, setLayerVisible] = useState(true);

  // --- Search ------------------------------------------------------------
  const [searchValue, setSearchValue] = useState("");
  const [searchHint, setSearchHint] = useState<string | null>(null);

  // --- Refs --------------------------------------------------------------
  const mapRef = useRef<maplibregl.Map | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const crossfadedRef = useRef(false);

  // GSAP scoping refs
  const rootRef = useRef<HTMLDivElement | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);
  const mapWrapperRef = useRef<HTMLDivElement | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // Ensure NEXT_PUBLIC_API_URL is read at least once.
  const apiBase = getApiBase();

  // -------------------------------------------------------------------------
  // Capture l'instance MapLibre interne de MapView (pont par evenement).
  // -------------------------------------------------------------------------
  useEffect(() => {
    function onReady(evt: Event) {
      const detail = (evt as CustomEvent<{ map: maplibregl.Map }>).detail;
      if (detail?.map) mapRef.current = detail.map;
    }
    window.addEventListener("carte-map-ready", onReady as EventListener);
    return () =>
      window.removeEventListener("carte-map-ready", onReady as EventListener);
  }, []);

  // -------------------------------------------------------------------------
  // Chargement de la PREVISUALISATION (asset statique) — une seule fois.
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    const ctrl = new AbortController();
    (async () => {
      try {
        const res = await fetch(PREVIEW_URL, { signal: ctrl.signal });
        if (!res.ok) throw new Error(`Preview: ${res.status}`);
        const data = (await res.json()) as SegmentCollection;
        if (!cancelled) setPreviewGeojson(data);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        console.warn("Preview evolution: dataset indisponible", err);
      }
    })();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [hydrated]);

  // -------------------------------------------------------------------------
  // Entrance animation (aside + map wrapper).
  // -------------------------------------------------------------------------
  useGSAP(
    () => {
      if (!hydrated || !asideRef.current || !mapWrapperRef.current) return;
      const tl = gsap.timeline();
      tl.from(asideRef.current, {
        x: -24,
        autoAlpha: 0,
        duration: 0.45,
        ease: "power2.out",
      }).from(
        mapWrapperRef.current,
        { autoAlpha: 0, duration: 0.5, ease: "power2.out" },
        "<0.05",
      );
    },
    { scope: rootRef, dependencies: [hydrated] },
  );

  // -------------------------------------------------------------------------
  // Upload des 2 cartes (multipart : file_t1, file_t2)
  // -------------------------------------------------------------------------
  const handleUpload = useCallback(async () => {
    if (!fileT1 || !fileT2) {
      toast.error(
        "Chargez les deux cartes (annee 1 = T1 et annee 2 = T2/base).",
      );
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file_t1", fileT1);
      form.append("file_t2", fileT2);
      const data = await apiClient.postForm<UploadResponse>(
        "/api/evolution/upload",
        form,
        { timeoutMs: 10 * 60_000 },
      );
      setSessionId(data.session_id);
      // Reset any previous run results when a new pair is uploaded.
      setRealGeojson(null);
      crossfadedRef.current = false;
      setProgress(0);
      setStage("");
      setPhase("upload");
      toast.success(
        "Cartes T1 et T2 chargees. Vous pouvez generer l'evolution.",
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Upload echoue : ${message}`);
    } finally {
      setUploading(false);
    }
  }, [fileT1, fileT2]);

  // -------------------------------------------------------------------------
  // Fetch du resultat reel (streamed) + crossfade GSAP preview -> real.
  // -------------------------------------------------------------------------
  const loadRealResult = useCallback(async (id: string) => {
    setResultLoading(true);
    setResultProgress(0);
    const ctrl = new AbortController();
    try {
      const token = getToken();
      const url = `${getApiBase()}/api/evolution/result/${encodeURIComponent(id)}`;
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: ctrl.signal,
        credentials: "include",
      });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try {
          const data = await res.json();
          if (data?.detail) detail = String(data.detail);
        } catch {
          // ignore
        }
        throw new Error(detail);
      }

      const total = Number(res.headers.get("Content-Length") || 0);
      const reader = res.body?.getReader();
      let data: SegmentCollection;
      if (reader && total > 0) {
        const chunks: Uint8Array[] = [];
        let received = 0;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value) {
            chunks.push(value);
            received += value.length;
            setResultProgress(Math.min(99, Math.round((received / total) * 100)));
          }
        }
        const blob = new Blob(chunks as BlobPart[], {
          type: "application/json",
        });
        data = JSON.parse(await blob.text()) as SegmentCollection;
      } else {
        data = (await res.json()) as SegmentCollection;
      }
      setResultProgress(100);

      // ---- Crossfade GSAP preview -> real -------------------------------
      const map = mapRef.current;
      const reduced = prefersReducedMotion();
      if (!map || reduced || !map.getLayer(REAL_LAYER_ID)) {
        // Pas de carte prete (ou motion reduit) : swap instantane.
        setRealGeojson(data);
        crossfadedRef.current = true;
      } else {
        // 1. fade out la preview, 2. swap geojson, 3. fade in via opacity expr.
        const obj = { o: 1 };
        gsap.to(obj, {
          o: 0,
          duration: 0.4,
          ease: "power2.out",
          onUpdate: () => {
            try {
              if (map.getLayer(REAL_LAYER_ID)) {
                map.setPaintProperty(
                  REAL_LAYER_ID,
                  "line-opacity",
                  obj.o * 0.85,
                );
              }
            } catch {
              /* layer gone */
            }
          },
          onComplete: () => {
            crossfadedRef.current = true;
            // Le swap declenche le re-render MapView qui reposera l'expression
            // d'opacite reelle (buildEvolutionOpacityExpression) via les
            // paintOverrides — fade-in implicite vers la carte reelle.
            setRealGeojson(data);
          },
        });
      }
    } catch (err: unknown) {
      if ((err as Error).name === "AbortError") return;
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Chargement du resultat echoue : ${message}`);
    } finally {
      setResultLoading(false);
    }
  }, []);

  // -------------------------------------------------------------------------
  // Polling du statut (le calcul matching + BAN est LONG)
  // -------------------------------------------------------------------------
  const startPolling = useCallback(
    (id: string) => {
      stopPolling();
      const tick = async () => {
        try {
          const st = await apiClient.get<StatusResponse>(
            `/api/evolution/status/${encodeURIComponent(id)}`,
          );
          setStage(st.stage ?? "");
          setProgress(Math.max(0, Math.min(100, st.progress ?? 0)));

          if (st.error) {
            stopPolling();
            setGenerating(false);
            setPhase("upload");
            toast.error(`Generation echouee : ${st.error}`);
            return;
          }
          if (st.done) {
            stopPolling();
            setGenerating(false);
            setProgress(100);
            setPhase("ready");
            toast.success("Carte d'evolution generee. Affichage du reel...");
            void loadRealResult(id);
          }
        } catch (err: unknown) {
          stopPolling();
          setGenerating(false);
          setPhase("upload");
          const message =
            err instanceof Error ? err.message : "Erreur inconnue";
          toast.error(`Suivi du statut interrompu : ${message}`);
        }
      };
      void tick();
      pollRef.current = setInterval(() => void tick(), POLL_INTERVAL_MS);
    },
    [stopPolling, loadRealResult],
  );

  // -------------------------------------------------------------------------
  // Lancement de la generation (background cote backend)
  // -------------------------------------------------------------------------
  const handleGenerate = useCallback(async () => {
    if (!sessionId) {
      toast.error("Chargez d'abord les deux cartes.");
      return;
    }
    setGenerating(true);
    setRealGeojson(null);
    crossfadedRef.current = false;
    setProgress(0);
    setStage("Initialisation...");
    setPhase("generating");
    try {
      const res = await apiClient.post<GenerateResponse>(
        "/api/evolution/generate",
        {
          session_id: sessionId,
          use_ban: useBan,
          plancher_t1: plancherT1,
          include_new: includeNew,
        },
      );
      if (!res.started) {
        setGenerating(false);
        setPhase("upload");
        toast.error("Le backend n'a pas demarre la generation.");
        return;
      }
      startPolling(res.session_id ?? sessionId);
    } catch (err: unknown) {
      setGenerating(false);
      setPhase("upload");
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Generation echouee : ${message}`);
    }
  }, [sessionId, useBan, plancherT1, includeNew, startPolling]);

  // -------------------------------------------------------------------------
  // Telechargement du GeoJSON resultat
  // -------------------------------------------------------------------------
  const handleDownload = useCallback(() => {
    if (!sessionId) return;
    apiClient
      .download(
        `/api/evolution/download/${sessionId}`,
        `evolution_debits_${sessionId.slice(0, 8)}.geojson`,
      )
      .catch((err: Error) =>
        toast.error(`Telechargement echoue : ${err.message}`),
      );
  }, [sessionId]);

  // Reset complet du couple de cartes
  const clearPair = useCallback(() => {
    stopPolling();
    setFileT1(null);
    setFileT2(null);
    setSessionId(null);
    setGenerating(false);
    setRealGeojson(null);
    crossfadedRef.current = false;
    setProgress(0);
    setStage("");
    setPhase("upload");
  }, [stopPolling]);

  // -------------------------------------------------------------------------
  // Paint overrides + filter (drives MapView). En preview : interactions de
  // legende reduites mais coloration dJOr identique.
  // -------------------------------------------------------------------------
  const paintOverrides = useMemo<MapViewPaintOverrides>(
    () => ({
      lineColor: buildEvolutionColorExpression(thresholds),
      lineWidth: buildEvolutionLineWidthExpression(),
      lineOpacity: buildEvolutionOpacityExpression(),
    }),
    [thresholds],
  );

  const paintFilter = useMemo<unknown[] | null>(
    () => buildEvolutionFilter(visibleBuckets, showNeutral, thresholds),
    [visibleBuckets, showNeutral, thresholds],
  );

  const toggleBucket = useCallback((index: number) => {
    setVisibleBuckets((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  // -------------------------------------------------------------------------
  // KPIs (sur le dataset reel uniquement)
  // -------------------------------------------------------------------------
  const kpis = useMemo<EvolutionKpis>(() => {
    if (!realGeojson) {
      return {
        total: 0,
        hausses: 0,
        baisses: 0,
        significatifs: 0,
        medianJor: null,
      };
    }
    return computeKpis(realGeojson.features);
  }, [realGeojson]);

  const legendCounts = useMemo<{ buckets: number[]; neutral: number }>(() => {
    const buckets = [0, 0, 0, 0];
    let neutral = 0;
    const src = realGeojson ?? previewGeojson;
    if (src) {
      for (const f of src.features) {
        const raw = f.properties?.dJOr;
        const idx = bucketIndexOf(raw == null ? null : Number(raw), thresholds);
        if (idx == null) neutral += 1;
        else buckets[idx] += 1;
      }
    }
    return { buckets, neutral };
  }, [realGeojson, previewGeojson, thresholds]);

  // -------------------------------------------------------------------------
  // Search by agregId (real dataset)
  // -------------------------------------------------------------------------
  const handleSearch = useCallback(() => {
    if (!realGeojson || !searchValue.trim()) return;
    const needle = searchValue.trim();
    const match = realGeojson.features.find((f) => {
      const id = String(f.properties?.agregId ?? "");
      return id === needle || id.includes(needle);
    });
    if (!match) {
      setSearchHint(`Aucun troncon avec agregId contenant "${needle}".`);
      return;
    }
    const center = featureCentroid(match);
    if (!center) {
      setSearchHint("Troncon trouve mais geometrie invalide.");
      return;
    }
    setSearchHint(`Troncon ${match.properties?.agregId} centre sur la carte.`);

    const map = mapRef.current;
    if (!map) return;

    const reduced = prefersReducedMotion();
    map.flyTo({
      center: center as [number, number],
      zoom: 16,
      duration: reduced ? 0 : 1200,
      essential: true,
    });

    setTimeout(
      () => {
        const props = (match.properties ?? {}) as GeoJsonProperties;
        new maplibregl.Popup({
          closeButton: true,
          maxWidth: "300px",
          offset: 8,
        })
          .setLngLat(center as [number, number])
          .setHTML(renderEvolutionPopup(props))
          .addTo(map);
      },
      reduced ? 0 : 1250,
    );
  }, [realGeojson, searchValue]);

  const handleResetFilters = useCallback(() => {
    setThresholds([...DEFAULT_THRESHOLDS]);
    setVisibleBuckets(new Set([0, 1, 2, 3]));
    setShowNeutral(true);
    setLayerVisible(true);
    setSearchValue("");
    setSearchHint(null);
  }, []);

  const canUpload = !!fileT1 && !!fileT2 && !uploading;
  const canGenerate = !!sessionId && !generating;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  if (!hydrated) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-3rem)]">
        <Loader2 className="animate-spin text-accent" size={24} />
      </div>
    );
  }

  return (
    <div ref={rootRef} className="flex flex-col min-h-[calc(100vh-3rem)]">
      {/* Header */}
      <header
        className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80"
        role="banner"
      >
        <div className="max-w-[1600px] mx-auto px-4 py-3 flex items-center gap-4">
          <button
            type="button"
            onClick={() => router.push("/")}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-text-muted hover:text-text hover:bg-bg-elevated transition-colors text-xs font-medium cursor-pointer"
            aria-label="Retour a l'accueil"
          >
            <ArrowLeft size={14} />
            <span>Accueil</span>
          </button>

          <div className="hidden sm:block w-px h-5 bg-border" aria-hidden />

          <div className="flex items-center gap-2 min-w-0">
            <GitCompareArrows size={16} className="text-accent shrink-0" />
            <h1 className="text-sm font-semibold text-text truncate">
              Carte d&apos;evolution des debits
            </h1>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {sessionId && (
              <span className="hidden md:inline text-[11px] text-text-muted font-mono">
                session {sessionId.slice(0, 8)}
              </span>
            )}
            {showingReal && (
              <button
                type="button"
                onClick={handleDownload}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium cursor-pointer transition-colors bg-success text-white hover:bg-emerald-600"
                title="Telecharger le geojson"
              >
                <Download size={14} />
                <span className="hidden sm:inline">Telecharger geojson</span>
              </button>
            )}
          </div>
        </div>
      </header>

      {/* KPI row (real dataset only) */}
      {showingReal && (
        <section
          className="border-b border-border bg-bg-elevated/30"
          aria-label="Indicateurs cle"
        >
          <div className="max-w-[1600px] mx-auto px-4 py-3 grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard
              label="Troncons"
              value={NF_FR.format(kpis.total)}
              icon={<Layers />}
              hint={`${NF_FR.format(kpis.significatifs)} significatifs`}
            />
            <KpiCard
              label="En hausse"
              value={NF_FR.format(kpis.hausses)}
              icon={<TrendingUp />}
            />
            <KpiCard
              label="En baisse"
              value={NF_FR.format(kpis.baisses)}
              icon={<TrendingUp className="rotate-180" />}
            />
            <KpiCard
              label="Evolution mediane"
              value={fmtPct(kpis.medianJor)}
              icon={<TrendingUp />}
            />
          </div>
        </section>
      )}

      {/* Bandeau + Map unifie */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0">
        {/* Sidebar (controles d'upload/options OU recherche/legende) */}
        <aside
          ref={asideRef}
          className="w-full lg:w-[380px] lg:shrink-0 lg:sticky lg:top-12 lg:self-start border-r border-border bg-bg-elevated/40 px-4 py-4 space-y-4 overflow-y-auto"
          aria-label={
            showingReal
              ? "Recherche et legende"
              : "Chargement et parametres de l'evolution"
          }
          style={{
            maxHeight: showingReal ? "calc(100vh - 9rem)" : undefined,
          }}
        >
          {!showingReal && (
            <ControlsPanel
              fileT1={fileT1}
              fileT2={fileT2}
              uploading={uploading}
              sessionId={sessionId}
              useBan={useBan}
              plancherT1={plancherT1}
              includeNew={includeNew}
              generating={generating}
              stage={stage}
              progress={progress}
              canUpload={canUpload}
              canGenerate={canGenerate}
              phase={phase}
              onFileT1={setFileT1}
              onFileT2={setFileT2}
              onUpload={handleUpload}
              onClearPair={clearPair}
              onUseBanChange={setUseBan}
              onPlancherChange={setPlancherT1}
              onIncludeNewChange={setIncludeNew}
              onGenerate={handleGenerate}
            />
          )}

          {showingReal && (
            <ReadySidebar
              searchValue={searchValue}
              searchHint={searchHint}
              onSearchChange={(v) => {
                setSearchValue(v);
                setSearchHint(null);
              }}
              onSearchSubmit={handleSearch}
              onResetFilters={handleResetFilters}
              hasGeojson={!!realGeojson}
            />
          )}
        </aside>

        {/* Map (single instance via MapView) */}
        <section
          ref={mapWrapperRef}
          role="region"
          className="flex-1 relative min-h-[480px] lg:min-h-0 min-w-0 bg-bg-elevated"
          aria-label="Carte interactive de l'evolution des debits"
        >
          {/* Badge "Apercu" pendant les phases non-reelles */}
          {!showingReal && (
            <div
              className="absolute top-3 left-1/2 -translate-x-1/2 z-10 pointer-events-none"
              role="status"
              aria-live="polite"
            >
              <NeonBorder
                tone="accent"
                speed={phase === "generating" ? 1.8 : 3.4}
                rotate={false}
                className="rounded-full"
              >
                <div className="px-3 py-1.5 rounded-full flex items-center gap-2">
                  <Eye size={12} aria-hidden className="text-accent" />
                  <ShimmerText variant="neon-white" className="text-xs">
                    {phase === "generating"
                      ? "Apercu Lyon — generation en cours, patiente quelques instants"
                      : "Apercu Lyon — charge tes 2 cartes pour passer en mode reel"}
                  </ShimmerText>
                </div>
              </NeonBorder>
            </div>
          )}

          {/* Overlay de chargement du resultat reel (avant crossfade) */}
          {resultLoading && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-bg/60 backdrop-blur-sm pointer-events-none">
              <Loader2 className="animate-spin text-accent" size={28} />
              <p className="mt-3 text-xs text-text-muted">
                Chargement de la carte reelle...
              </p>
              {resultProgress > 0 && (
                <div className="mt-3 w-56 h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                  <div
                    className="h-full bg-accent transition-[width] duration-200"
                    style={{ width: `${resultProgress}%` }}
                  />
                </div>
              )}
            </div>
          )}

          <MapView
            geojson={activeGeojson}
            theme="dark"
            className="h-full"
            paintOverrides={paintOverrides}
            paintFilter={showingReal ? paintFilter : null}
            layerVisible={layerVisible}
            renderPopup={renderEvolutionPopup}
            hideDefaultLegend
          />

          {/* Legende divergente interactive — uniquement en mode reel */}
          {showingReal && realGeojson && (
            <EvolutionLegend
              thresholds={thresholds}
              onThresholdsChange={setThresholds}
              visibleBuckets={visibleBuckets}
              onToggleBucket={toggleBucket}
              showNeutral={showNeutral}
              onToggleNeutral={() => setShowNeutral((v) => !v)}
              layerVisible={layerVisible}
              onToggleLayer={() => setLayerVisible((v) => !v)}
              counts={legendCounts}
            />
          )}

          {apiBase && showingReal && (
            <p className="absolute bottom-1 left-2 z-10 text-[9px] text-text-subtle/70 pointer-events-none">
              API : {apiBase} /api/evolution
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

// ===========================================================================
// Sidebar — controles upload + options + generation (phases non-reelles)
// ===========================================================================

function ControlsPanel({
  fileT1,
  fileT2,
  uploading,
  sessionId,
  useBan,
  plancherT1,
  includeNew,
  generating,
  stage,
  progress,
  canUpload,
  canGenerate,
  phase,
  onFileT1,
  onFileT2,
  onUpload,
  onClearPair,
  onUseBanChange,
  onPlancherChange,
  onIncludeNewChange,
  onGenerate,
}: {
  fileT1: File | null;
  fileT2: File | null;
  uploading: boolean;
  sessionId: string | null;
  useBan: boolean;
  plancherT1: number;
  includeNew: boolean;
  generating: boolean;
  stage: string;
  progress: number;
  canUpload: boolean;
  canGenerate: boolean;
  phase: Phase;
  onFileT1: (f: File | null) => void;
  onFileT2: (f: File | null) => void;
  onUpload: () => void;
  onClearPair: () => void;
  onUseBanChange: (v: boolean) => void;
  onPlancherChange: (v: number) => void;
  onIncludeNewChange: (v: boolean) => void;
  onGenerate: () => void;
}) {
  return (
    <div className="space-y-4">
      {/* Intro */}
      <div className="rounded-xl border border-accent/20 bg-gradient-to-br from-accent-subtle to-transparent p-4 space-y-2">
        <div className="flex items-center gap-2">
          <GitCompareArrows size={14} className="text-accent shrink-0" />
          <h2 className="text-sm font-semibold text-text">
            Compare deux annees de debits
          </h2>
        </div>
        <p className="text-[12px] text-text-muted leading-relaxed">
          Charge deux cartes redressees (annee 1 = T1, annee 2 = T2/base). La
          carte d&apos;evolution colore chaque troncon par{" "}
          <span className="font-mono text-accent">dJOr</span> (variation en
          véh/j). JOr (%) = round((T2 − T1) / T1 × 100, 2).
        </p>
      </div>

      {/* Etape 1 — Uploads */}
      <div className="rounded-xl border border-border bg-bg-elevated/50 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-accent-subtle flex items-center justify-center text-accent text-[11px] font-bold">
            1
          </div>
          <h3 className="text-[13px] font-semibold text-text">
            Cartes a comparer (GeoJSON)
          </h3>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-[11px] font-semibold text-text-muted">
            <Calendar size={13} className="text-sky-400" />
            <span>Carte annee 1 — T1</span>
          </div>
          <DropZone
            file={fileT1}
            onFile={onFileT1}
            onClear={() => onFileT1(null)}
            accept={ACCEPT_GEOJSON}
            label="Deposez la carte de l'annee 1 (T1)"
            description=".geojson ou .json — ex 2023.geojson"
          />
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-[11px] font-semibold text-text-muted">
            <Calendar size={13} className="text-emerald-400" />
            <span>Carte annee 2 — T2 (base)</span>
          </div>
          <DropZone
            file={fileT2}
            onFile={onFileT2}
            onClear={() => onFileT2(null)}
            accept={ACCEPT_GEOJSON}
            label="Deposez la carte de l'annee 2 (T2, base)"
            description=".geojson ou .json — ex 2024.geojson"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <NeonButton
            onClick={onUpload}
            disabled={!canUpload}
            icon={
              uploading ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Layers size={14} />
              )
            }
          >
            {uploading ? "Chargement..." : "Charger les deux cartes"}
          </NeonButton>

          {sessionId && (
            <>
              <span className="inline-flex items-center gap-1.5 text-[11px] text-emerald-400">
                <CheckCircle2 size={13} />
                Session prete
              </span>
              <button
                type="button"
                onClick={onClearPair}
                className="text-[11px] text-text-muted hover:text-text underline-offset-2 hover:underline cursor-pointer"
              >
                Reinitialiser
              </button>
            </>
          )}
        </div>
      </div>

      {/* Etape 2 — Options */}
      <div className="rounded-xl border border-border bg-bg-elevated/50 p-4 space-y-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-accent-subtle flex items-center justify-center text-accent text-[11px] font-bold">
            2
          </div>
          <h3 className="text-[13px] font-semibold text-text">
            Parametres de l&apos;appariement
          </h3>
        </div>

        {/* Plancher emergent */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label
              htmlFor="evo-plancher"
              className="text-[11px] text-text-muted flex items-center gap-1.5"
            >
              <TrendingUp size={12} className="text-violet-400" />
              Plancher T1 (garde-fou « emergent »)
            </label>
            <span className="text-[11px] text-accent font-semibold tabular-nums">
              {NF_FR.format(plancherT1)} v/j
            </span>
          </div>
          <input
            id="evo-plancher"
            type="range"
            min={0}
            max={500}
            step={10}
            value={plancherT1}
            onChange={(e) => onPlancherChange(Number(e.target.value))}
            className="w-full h-1.5 rounded-full appearance-none bg-bg-subtle cursor-pointer accent-indigo-500"
            aria-label="Plancher T1 en vehicules par jour"
          />
          <p className="text-[10px] text-text-subtle leading-snug">
            Un troncon dont T1 est inferieur au plancher est classe{" "}
            <span className="text-violet-300">emergent</span> : pas de
            pourcentage (JOr = null), seul le delta absolu dJOr est conserve.
          </p>
        </div>

        {/* BAN */}
        <label className="flex items-start gap-2.5 cursor-pointer group">
          <input
            type="checkbox"
            checked={useBan}
            onChange={(e) => onUseBanChange(e.target.checked)}
            className="mt-0.5 w-3.5 h-3.5 rounded border-border accent-emerald-500 cursor-pointer"
          />
          <div className="flex-1">
            <span className="text-[11px] font-medium text-text-muted group-hover:text-emerald-300 transition-colors flex items-center gap-1.5">
              <ShieldCheck size={12} className="text-emerald-400" />
              Verification BAN (filtre de securite)
            </span>
            <p className="text-[10px] text-text-subtle mt-0.5 leading-snug">
              Reverse-geocoding des points milieux. Un MISMATCH retrograde un
              appariement GEOM_AUTO en GEOM_VERIF. Etape plus longue mais plus
              fiable.
            </p>
          </div>
        </label>

        {/* include_new */}
        <label className="flex items-start gap-2.5 cursor-pointer group">
          <input
            type="checkbox"
            checked={includeNew}
            onChange={(e) => onIncludeNewChange(e.target.checked)}
            className="mt-0.5 w-3.5 h-3.5 rounded border-border accent-sky-500 cursor-pointer"
          />
          <div className="flex-1">
            <span className="text-[11px] font-medium text-text-muted group-hover:text-sky-300 transition-colors flex items-center gap-1.5">
              <GitCompareArrows size={12} className="text-sky-400" />
              Inclure les troncons « nouveaux » (T2 seul)
            </span>
            <p className="text-[10px] text-text-subtle mt-0.5 leading-snug">
              Emet les troncons de la base T2 sans appariement T1 (categorie{" "}
              <span className="text-sky-300">nouveau</span>). Recommande pour la
              completude.
            </p>
          </div>
        </label>
      </div>

      {/* Etape 3 — Generation */}
      <div className="rounded-xl border border-border bg-bg-elevated/50 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-accent-subtle flex items-center justify-center text-accent text-[11px] font-bold">
            3
          </div>
          <h3 className="text-[13px] font-semibold text-text">
            Generation de la carte
          </h3>
        </div>

        {!sessionId && (
          <p className="text-[11px] text-text-muted">
            Chargez d&apos;abord les deux cartes (Etape 1) pour activer la
            generation.
          </p>
        )}

        {canGenerate ? (
          <NeonBorder tone="accent" speed={2.6} className="rounded-md">
            <MagneticButton
              variant="primary"
              size="md"
              onClick={onGenerate}
              className="w-full"
            >
              <GitCompareArrows size={16} />
              Generer l&apos;evolution
            </MagneticButton>
          </NeonBorder>
        ) : (
          <NeonButton
            onClick={onGenerate}
            disabled={!canGenerate}
            icon={
              generating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <GitCompareArrows size={14} />
              )
            }
          >
            {generating ? "Generation en cours..." : "Generer l'evolution"}
          </NeonButton>
        )}

        {(generating || (progress > 0 && phase === "generating")) && (
          <div className="space-y-2 pt-1">
            <div className="flex items-center justify-between text-[11px] text-text-muted">
              <span className="flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin text-accent" />
                {stage || "Traitement..."}
              </span>
              <span className="tabular-nums text-accent font-semibold">
                {Math.round(progress)}%
              </span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-bg-subtle overflow-hidden">
              <div
                className="h-full bg-accent transition-[width] duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-[10px] text-text-subtle leading-snug">
              Appariement N1 (cle exacte) puis N2 (map-matching geometrique)
              {useBan ? " puis N3 (verification BAN)" : ""}. Plusieurs minutes
              possibles.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// Sidebar — recherche + aide (phase reelle)
// ===========================================================================

function ReadySidebar({
  searchValue,
  searchHint,
  onSearchChange,
  onSearchSubmit,
  onResetFilters,
  hasGeojson,
}: {
  searchValue: string;
  searchHint: string | null;
  onSearchChange: (v: string) => void;
  onSearchSubmit: () => void;
  onResetFilters: () => void;
  hasGeojson: boolean;
}) {
  return (
    <>
      {/* Search */}
      <div className="surface-elevated p-3 space-y-2">
        <div className="flex items-center gap-2">
          <Search size={12} className="text-accent" />
          <h4 className="text-[11px] font-semibold text-text uppercase tracking-wide">
            Recherche agregId
          </h4>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={searchValue}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSearchSubmit();
            }}
            placeholder="Identifiant complet ou partiel"
            disabled={!hasGeojson}
            className="flex-1 h-8 rounded border border-border bg-bg-elevated px-2 text-xs text-text outline-none focus:border-accent disabled:opacity-50"
            aria-label="Identifiant agregId"
          />
          <button
            type="button"
            onClick={onSearchSubmit}
            disabled={!hasGeojson || !searchValue.trim()}
            className="inline-flex items-center justify-center w-8 h-8 rounded bg-accent text-accent-fg hover:bg-indigo-600 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
            aria-label="Lancer la recherche"
            title="Lancer la recherche"
          >
            <Crosshair size={14} />
          </button>
        </div>
        {searchHint && (
          <p className="text-[10px] text-text-muted">{searchHint}</p>
        )}
      </div>

      {/* Reset filters */}
      <button
        type="button"
        onClick={onResetFilters}
        className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-xs bg-bg-elevated text-text-muted border border-border hover:text-text transition-colors cursor-pointer"
      >
        <RotateCcw size={14} />
        Reinitialiser seuils + filtres
      </button>

      {/* Tip */}
      <div className="rounded border border-border bg-bg-elevated/50 px-3 py-2.5 text-[10px] text-text-muted leading-relaxed">
        <p>
          <FilterIcon size={10} className="inline -mt-0.5 mr-1" />
          Coloration par dJOr (variation en véh/j) : bleu = baisse, orange =
          hausse (centré sur 0). Les seuils sont modifiables dans la légende.
          Les troncons non significatifs sont atténués. Cliquez sur un troncon
          pour le détail dJOr/JOr/T1/T2.
        </p>
      </div>
    </>
  );
}
