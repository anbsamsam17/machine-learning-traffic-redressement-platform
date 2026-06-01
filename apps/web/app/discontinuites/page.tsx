"use client";

/**
 * Analyse des discontinuites TVr+DPL — module independant.
 *
 * UX unifie (refonte 2026-05) :
 *  - Bandeau gauche TOUJOURS visible (~380px) :
 *      * Phase upload : Sam intro + 2 dropzones (segments + FCD parquet)
 *        + bouton "Lancer l'analyse" desactive tant que l'upload n'est pas OK.
 *      * Phase analyzing : indicateur de progression + dropzones desactivees.
 *      * Phase ready : panneaux Causes / Topologie / Severite / Recherche.
 *  - Carte droite TOUJOURS visible :
 *      * Phases upload + analyzing : preview Lyon (interactions desactivees).
 *      * Phase ready : noeuds reels, popup + selection.
 *  - Crossfade GSAP preview -> reel. UNE SEULE instance MapLibre.
 *
 * Endpoints backend consommes :
 *  - POST /api/discontinuites/upload-geojson  (multipart: file)
 *  - POST /api/discontinuites/upload-fcd      (multipart: file + session_id)
 *  - POST /api/discontinuites/analyze         (long-running)
 *  - GET  /api/discontinuites/nodes/{sid}     (Point FeatureCollection)
 *
 * Refonte structurelle (2026-05) :
 *  - NodePanel + FluxCell -> @/components/discontinuites/NodePanel
 *  - CauseCard            -> @/components/discontinuites/CauseCard
 *  - Hook MapLibre        -> @/lib/hooks/use-map-instance
 *  - Paint exprs + layers -> @/lib/map/setup (buildCausePaintExprs,
 *                            installNodeMarkers, removeNodeMarkers)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Upload,
  Loader2,
  AlertTriangle,
  AlertCircle,
  Search,
  Crosshair,
  RotateCcw,
  Eye,
  CheckCircle2,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";

import { DropZone } from "@/components/upload/drop-zone";
import { BasemapSwitcher } from "@/components/map/BasemapSwitcher";
import { apiClient, ApiError } from "@/lib/api";
import { getApiBase } from "@/lib/api-url";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { useMapInstance } from "@/lib/hooks/use-map-instance";
import {
  buildCausePaintExprs,
  installNodeMarkers,
  removeNodeMarkers,
  type CauseKey,
  type TopologyKey,
} from "@/lib/map/setup";
import {
  NodePanel,
  type SelectedNode,
} from "@/components/discontinuites/NodePanel";
import { CauseCard } from "@/components/discontinuites/CauseCard";
// UX5 — premium CTA + KPI badges
import {
  MagneticButton,
  ShimmerText,
  NeonBorder,
  RevealOnScroll,
} from "@/components/ui";

// ---------------------------------------------------------------------------
// Types backend
// ---------------------------------------------------------------------------

interface UploadGeojsonResponse {
  session_id: string;
  filename: string;
  n_features: number;
  bbox: [number, number, number, number] | null;
  file_size_mb: number;
  columns?: string[];
}

interface UploadFcdResponse {
  session_id: string;
  n_segments: number;
  columns_detected: string[];
  file_size_mb: number;
}

interface AnalyzeResponse {
  session_id: string;
  n_nodes_flagged: number;
  n_causes: Record<string, number>;
  n_topology: Record<string, number>;
  pipeline_duration_s: number;
  bbox?: [number, number, number, number] | null;
  fcd_joined?: boolean;
  fcd_columns_count?: number;
  warning?: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LYON_CENTER: [number, number] = [4.85, 45.75];
const LYON_ZOOM = 11;
const NF_FR = new Intl.NumberFormat("fr-FR");

const CAUSE_ORDER: CauseKey[] = [
  "FCD_TV_cliff",
  "FCD_PL_cliff",
  "Coverage_gap",
  "Distance_anomaly",
  "RAMP_asymmetry",
  "ROUNDABOUT_asymmetry",
  "FC_transition",
  "Unexplained",
];

const TOPO_ORDER: TopologyKey[] = ["Bretelle", "Carrefour", "Continuite"];

const PALETTE: Record<CauseKey, string> = {
  FCD_TV_cliff: "#E41A1C",
  FCD_PL_cliff: "#B30000",
  Coverage_gap: "#7B1FA2",
  Distance_anomaly: "#FF7F00",
  RAMP_asymmetry: "#FFB000",
  ROUNDABOUT_asymmetry: "#A65628",
  FC_transition: "#377EB8",
  Unexplained: "#999999",
};

const TOPO_PALETTE: Record<TopologyKey, string> = {
  Bretelle: "#87CEEB",
  Carrefour: "#4682B4",
  Continuite: "#FFA07A",
};

const CAUSE_LABELS_FR: Record<CauseKey, string> = {
  FCD_TV_cliff: "Falaise FCD VL",
  FCD_PL_cliff: "Falaise FCD PL",
  Coverage_gap: "Trou de couverture FCD",
  Distance_anomaly: "Anomalie de distance",
  RAMP_asymmetry: "Bretelle asymetrique",
  ROUNDABOUT_asymmetry: "Rond-point asymetrique",
  FC_transition: "Transition de classe fonctionnelle (legitime)",
  Unexplained: "Inexplique (a investiguer)",
};

const TOPO_LABELS_FR: Record<TopologyKey, string> = {
  Bretelle: "Bretelle",
  Carrefour: "Carrefour",
  Continuite: "Continuite segment",
};

// Fond de carte par defaut : Esri World Imagery (satellite, harmonise avec
// /visualisation). Le composant <BasemapSwitcher /> permet de basculer vers
// Voyager, Positron ou Dark Matter ; la preference est persistee en
// localStorage. Les constantes URL+attribution viennent de lib/map/basemaps.ts.

const MAP_ATTRIB_CSS = `
  .maplibregl-ctrl-attrib {
    background: rgba(255,255,255,.85) !important;
    color: #555 !important;
    font-size: 10px !important;
  }
  .maplibregl-ctrl-attrib a { color: #2563eb !important; }
`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtFR(n: number | null | undefined): string {
  if (n === null || n === undefined || !isFinite(Number(n))) return "—";
  return NF_FR.format(Math.round(Number(n)));
}

function fmtFRdec(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || !isFinite(Number(n))) return "—";
  return Number(n).toLocaleString("fr-FR", {
    maximumFractionDigits: d,
    minimumFractionDigits: 0,
  });
}

// ---------------------------------------------------------------------------
// KPI Card
// ---------------------------------------------------------------------------

const MONO = `ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace`;

function KpiCard({
  label,
  value,
  hint,
  accentColor,
}: {
  label: string;
  value: string;
  hint?: string;
  accentColor?: string;
}) {
  return (
    <div className="rounded-lg border border-[#1f2740] bg-[rgba(15,20,36,.6)] p-3 flex items-start gap-3">
      <div
        className="shrink-0 w-8 h-8 rounded flex items-center justify-center"
        style={{
          background: accentColor ? `${accentColor}22` : "rgba(255,176,0,0.12)",
          color: accentColor ?? "#FFB000",
        }}
      >
        <AlertCircle size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] uppercase tracking-wide text-[#a0b0d8] truncate">
          {label}
        </p>
        <p
          className="font-mono text-lg font-semibold mt-0.5 tabular-nums leading-none text-[#e6edf3] truncate"
          style={{ fontFamily: MONO }}
        >
          {value}
        </p>
        {hint && (
          <p className="text-[10px] text-[#7d8aa8] mt-1 truncate">{hint}</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type Phase = "upload" | "analyzing" | "ready";

export default function DiscontinuitesPage() {
  const router = useRouter();

  // --- Hydration gate ----------------------------------------------------
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
  }, []);

  // --- Upload + analyze --------------------------------------------------
  const [phase, setPhase] = useState<Phase>("upload");
  const [geoFile, setGeoFile] = useState<File | null>(null);
  const [geoUploading, setGeoUploading] = useState(false);
  const [geoUploadResp, setGeoUploadResp] =
    useState<UploadGeojsonResponse | null>(null);
  const [fcdFile, setFcdFile] = useState<File | null>(null);
  const [fcdUploading, setFcdUploading] = useState(false);
  const [fcdUploadResp, setFcdUploadResp] =
    useState<UploadFcdResponse | null>(null);
  const [analyzeResp, setAnalyzeResp] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // --- Map (single instance) --------------------------------------------
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const nodesDataRef = useRef<GeoJSON.FeatureCollection | null>(null);
  const [nodesLoaded, setNodesLoaded] = useState(false);
  const previewLoadedRef = useRef(false);
  const realLayersInstalledRef = useRef(false);

  // Hook MapLibre partage (cf. /lib/hooks/use-map-instance).
  // NavigationControl en top-right + ScaleControl en bottom-right (positions
  // historiques de /discontinuites — note : bottom-RIGHT et non bottom-LEFT).
  const { map: mapInstance, ready: mapReady } = useMapInstance({
    containerRef: mapContainerRef,
    center: LYON_CENTER,
    zoom: LYON_ZOOM,
    scalePosition: "bottom-right",
    devGlobalName: "__discoMap",
    enabled: hydrated,
    onReady: () => {
      if (
        typeof document !== "undefined" &&
        !document.getElementById("discontinuites-map-css")
      ) {
        const styleEl = document.createElement("style");
        styleEl.id = "discontinuites-map-css";
        styleEl.textContent = MAP_ATTRIB_CSS;
        document.head.appendChild(styleEl);
      }
    },
  });
  const mapRef = useRef<maplibregl.Map | null>(null);
  useEffect(() => {
    mapRef.current = mapInstance;
  }, [mapInstance]);

  // GSAP scoping refs
  const rootRef = useRef<HTMLDivElement | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);
  const mapWrapperRef = useRef<HTMLDivElement | null>(null);

  // --- Side panel state -------------------------------------------------
  const [selectedNode, setSelectedNode] = useState<SelectedNode | null>(null);
  const selectedNodeIdRef = useRef<string | number | null>(null);

  const [activeCauses, setActiveCauses] = useState<Set<CauseKey>>(
    () => new Set(CAUSE_ORDER),
  );
  const [activeTopos, setActiveTopos] = useState<Set<TopologyKey>>(
    () => new Set(TOPO_ORDER),
  );
  const [currentTier, setCurrentTier] = useState<"all" | "orange" | "red">("all");
  const [searchValue, setSearchValue] = useState("");
  const [searchHint, setSearchHint] = useState<string | null>(null);

  // KPIs
  const [causeCounts, setCauseCounts] = useState<Record<string, number>>({});
  const [topoCounts, setTopoCounts] = useState<Record<string, number>>({});
  const [totalNodes, setTotalNodes] = useState(0);
  const [visibleNodes, setVisibleNodes] = useState(0);

  // --- Sam welcome handled globally by <SamWidget /> + page-messages ----
  // (Removed local samNotify.welcome to avoid two Sam layers stacking.
  // The contextual bubble for /discontinuites lives in
  // `lib/sam/page-messages.ts` and is pushed by <SamPageBinder />.)

  // --- Entrance animations ----------------------------------------------
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

  // --- Upload handlers ---------------------------------------------------

  const handleUploadGeo = useCallback(async (file: File) => {
    setGeoFile(file);
    setGeoUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiClient.postForm<UploadGeojsonResponse>(
        "/api/discontinuites/upload-geojson",
        form,
        { timeoutMs: 5 * 60_000 },
      );
      setGeoUploadResp(res);
      toast.success(`GeoJSON charge : ${res.n_features} features`);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      toast.error(`Upload echoue : ${msg}`);
      setError(msg);
      setGeoFile(null);
    } finally {
      setGeoUploading(false);
    }
  }, []);

  const handleClearGeo = useCallback(() => {
    setGeoFile(null);
    setGeoUploadResp(null);
    setFcdFile(null);
    setFcdUploadResp(null);
  }, []);

  const handleUploadFcd = useCallback(
    async (file: File) => {
      if (!geoUploadResp) {
        toast.error(
          "Uploadez d'abord le reseau GeoJSON avant le parquet FCD.",
        );
        return;
      }
      setFcdFile(file);
      setFcdUploading(true);
      setError(null);
      try {
        const form = new FormData();
        form.append("file", file);
        form.append("session_id", geoUploadResp.session_id);
        const res = await apiClient.postForm<UploadFcdResponse>(
          "/api/discontinuites/upload-fcd",
          form,
          { timeoutMs: 5 * 60_000 },
        );
        setFcdUploadResp(res);
        toast.success(
          `Parquet FCD charge : ${res.n_segments} segments, ${res.columns_detected.length} colonnes joignables`,
        );
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.detail
            : err instanceof Error
              ? err.message
              : "Erreur inconnue";
        toast.error(`Upload FCD echoue : ${msg}`);
        setError(msg);
        setFcdFile(null);
      } finally {
        setFcdUploading(false);
      }
    },
    [geoUploadResp],
  );

  const handleClearFcd = useCallback(() => {
    setFcdFile(null);
    setFcdUploadResp(null);
  }, []);

  // --- Analyze (long running) -------------------------------------------

  const handleAnalyze = useCallback(async () => {
    if (!geoUploadResp) return;
    setPhase("analyzing");
    setError(null);
    try {
      const fd = new FormData();
      fd.append("session_id", geoUploadResp.session_id);
      const res = await apiClient.postForm<AnalyzeResponse>(
        "/api/discontinuites/analyze",
        fd,
        { timeoutMs: 5 * 60_000 },
      );
      setAnalyzeResp(res);
      toast.success(
        `Analyse terminee : ${fmtFR(res.n_nodes_flagged)} noeuds discontinus en ${fmtFRdec(res.pipeline_duration_s, 1)} s`,
      );
      setPhase("ready");
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      toast.error(`Analyse echouee : ${msg}`);
      setError(msg);
      setPhase("upload");
    }
  }, [geoUploadResp]);

  // --- Fetch nodes geojson once analyse OK -------------------------------

  useEffect(() => {
    if (phase !== "ready" || !analyzeResp || !geoUploadResp) return;
    let cancelled = false;
    const ctrl = new AbortController();

    async function loadNodes() {
      try {
        const token = getToken();
        const headers: HeadersInit = token
          ? { Authorization: `Bearer ${token}` }
          : {};
        const res = await fetch(
          `${getApiBase()}/api/discontinuites/nodes/${encodeURIComponent(geoUploadResp!.session_id)}`,
          { headers, credentials: "include", signal: ctrl.signal },
        );
        if (!res.ok) throw new Error(`Nodes: ${res.status}`);
        const data = (await res.json()) as GeoJSON.FeatureCollection;
        if (cancelled) return;

        data.features.forEach((f, i) => {
          if (f.id == null) {
            const nid = f.properties?.node_id;
            f.id = nid != null ? String(nid) : i;
          }
        });
        nodesDataRef.current = data;

        const cCounts: Record<string, number> = {};
        const tCounts: Record<string, number> = {};
        CAUSE_ORDER.forEach((c) => (cCounts[c] = 0));
        TOPO_ORDER.forEach((t) => (tCounts[t] = 0));
        data.features.forEach((f) => {
          const c = f.properties?.principal_cause as string;
          const t = f.properties?.topology as string;
          if (c) cCounts[c] = (cCounts[c] ?? 0) + 1;
          if (t) tCounts[t] = (tCounts[t] ?? 0) + 1;
        });
        setCauseCounts(cCounts);
        setTopoCounts(tCounts);
        setTotalNodes(data.features.length);
        setVisibleNodes(data.features.length);
        setNodesLoaded(true);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        const msg = err instanceof Error ? err.message : "Erreur inconnue";
        toast.error(`Chargement noeuds echoue : ${msg}`);
        setError(msg);
      }
    }

    loadNodes();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [phase, analyzeResp, geoUploadResp]);

  // --- Preview dataset + layers (sans click handlers) -------------------

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || phase === "ready" || previewLoadedRef.current)
      return;

    let cancelled = false;
    const ctrl = new AbortController();

    (async () => {
      try {
        const res = await fetch("/preview/discontinuites-lyon.geojson", {
          signal: ctrl.signal,
        });
        if (!res.ok) throw new Error(`Preview: ${res.status}`);
        const data = (await res.json()) as GeoJSON.FeatureCollection;
        if (cancelled || !mapRef.current) return;

        const exprs = buildCausePaintExprs(
          CAUSE_ORDER,
          PALETTE,
          TOPO_ORDER,
          TOPO_PALETTE,
        );

        if (!map.getSource("preview-nodes")) {
          map.addSource("preview-nodes", {
            type: "geojson",
            data: data as never,
          });
          // Preview : pas d'interaction de selection, donc strokeWidth fixe a 3.
          installNodeMarkers(map, {
            sourceId: "preview-nodes",
            idPrefix: "preview-nodes",
            exprs,
            selectableStroke: false,
          });
        }
        previewLoadedRef.current = true;
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        console.warn("Preview discontinuites: dataset indisponible", err);
      }
    })();

    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [mapReady, phase]);

  // --- Crossfade preview -> real -----------------------------------------
  const removePreviewLayers = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    const cleanup = () =>
      removeNodeMarkers(map, "preview-nodes", "preview-nodes");

    if (reduced || !map.getLayer("preview-nodes-circle")) {
      cleanup();
      return;
    }
    const obj = { o: 1 };
    gsap.to(obj, {
      o: 0,
      duration: 0.4,
      ease: "power2.out",
      onUpdate: () => {
        try {
          if (map.getLayer("preview-nodes-circle")) {
            map.setPaintProperty(
              "preview-nodes-circle",
              "circle-stroke-opacity",
              obj.o * 0.95,
            );
            map.setPaintProperty(
              "preview-nodes-circle",
              "circle-opacity",
              obj.o * 0.85,
            );
          }
          if (map.getLayer("preview-nodes-halo")) {
            map.setPaintProperty(
              "preview-nodes-halo",
              "circle-opacity",
              obj.o * 0.35,
            );
          }
        } catch {
          /* layers gone */
        }
      },
      onComplete: cleanup,
    });
  }, []);

  // --- Add real source + layers once nodes loaded + map ready -----------

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !nodesLoaded || !nodesDataRef.current) return;

    const data = nodesDataRef.current;
    const exprs = buildCausePaintExprs(
      CAUSE_ORDER,
      PALETTE,
      TOPO_ORDER,
      TOPO_PALETTE,
    );

    if (map.getSource("nodes")) {
      (map.getSource("nodes") as maplibregl.GeoJSONSource).setData(
        data as never,
      );
    } else {
      map.addSource("nodes", {
        type: "geojson",
        data: data as never,
        promoteId: "node_id",
      });

      installNodeMarkers(map, {
        sourceId: "nodes",
        idPrefix: "nodes",
        exprs,
        selectableStroke: true,
      });

      const canvas = map.getCanvas();
      map.on("mouseenter", "nodes-circle", () => {
        canvas.style.cursor = "pointer";
      });
      map.on("mouseleave", "nodes-circle", () => {
        canvas.style.cursor = "";
      });

      map.on("click", "nodes-circle", (e) => {
        const feat = e.features?.[0];
        if (!feat) return;
        const g = feat.geometry as GeoJSON.Geometry;
        if (g.type !== "Point") return;
        const c = g.coordinates as number[];
        const coords: [number, number] = [Number(c[0]), Number(c[1])];
        const props = (feat.properties ?? {}) as Record<string, unknown>;
        const fid =
          feat.id != null
            ? (feat.id as string | number)
            : (props.node_id as string | number | undefined) ?? "";
        setSelectedNode({ id: fid, coords, properties: props });

        const reduced =
          typeof window !== "undefined" &&
          window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        try {
          map.easeTo({
            center: coords,
            duration: reduced ? 0 : 320,
            padding: { right: 380, top: 0, bottom: 0, left: 0 },
          });
        } catch {
          /* ignore */
        }
      });

      map.on("click", (e) => {
        const hits = map.queryRenderedFeatures(e.point, {
          layers: ["nodes-circle"],
        });
        if (hits.length === 0) {
          setSelectedNode(null);
        }
      });
    }

    realLayersInstalledRef.current = true;
    removePreviewLayers();

    const bbox =
      analyzeResp?.bbox ?? geoUploadResp?.bbox ?? computeBboxFromFeatures(data);
    if (bbox && bbox.length === 4) {
      const reduced =
        typeof window !== "undefined" &&
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      map.fitBounds(
        [
          [bbox[0], bbox[1]],
          [bbox[2], bbox[3]],
        ],
        { padding: 60, maxZoom: 14, duration: reduced ? 0 : 800 },
      );
    }
  }, [mapReady, nodesLoaded, analyzeResp, geoUploadResp, removePreviewLayers]);

  // --- Filtres : causes + topo + tier + search ---------------------------

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !nodesLoaded) return;
    if (!map.getLayer("nodes-circle")) return;

    const causesIn = Array.from(activeCauses);
    const toposIn = Array.from(activeTopos);
    const filters: unknown[] = ["all"];
    filters.push(["in", ["get", "principal_cause"], ["literal", causesIn]]);
    filters.push(["in", ["get", "topology"], ["literal", toposIn]]);
    if (currentTier !== "all") {
      filters.push(["==", ["get", "tier"], currentTier]);
    }
    if (searchValue.trim()) {
      filters.push([
        "in",
        searchValue.trim(),
        ["to-string", ["get", "node_id"]],
      ]);
    }
    map.setFilter("nodes-circle", filters as never);

    if (currentTier === "all" || currentTier === "red") {
      map.setLayoutProperty("nodes-halo", "visibility", "visible");
      const haloFilter: unknown[] = [
        "all",
        ["==", ["get", "tier"], "red"],
        ["in", ["get", "principal_cause"], ["literal", causesIn]],
        ["in", ["get", "topology"], ["literal", toposIn]],
      ];
      if (searchValue.trim()) {
        haloFilter.push([
          "in",
          searchValue.trim(),
          ["to-string", ["get", "node_id"]],
        ]);
      }
      map.setFilter("nodes-halo", haloFilter as never);
    } else {
      map.setLayoutProperty("nodes-halo", "visibility", "none");
    }

    const data = nodesDataRef.current;
    if (data) {
      let n = 0;
      const needle = searchValue.trim();
      data.features.forEach((f) => {
        const p = f.properties as Record<string, unknown>;
        if (!activeCauses.has(p.principal_cause as CauseKey)) return;
        if (!activeTopos.has(p.topology as TopologyKey)) return;
        if (currentTier !== "all" && p.tier !== currentTier) return;
        if (needle && !String(p.node_id).includes(needle)) return;
        n += 1;
      });
      setVisibleNodes(n);
    }
  }, [
    activeCauses,
    activeTopos,
    currentTier,
    searchValue,
    mapReady,
    nodesLoaded,
  ]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedNode(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    if (nodesLoaded) {
      setSearchValue("");
      setSearchHint(null);
    }
  }, [nodesLoaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !nodesLoaded) return;
    if (!map.getSource("nodes")) return;

    const prevId = selectedNodeIdRef.current;
    if (prevId != null) {
      try {
        map.setFeatureState({ source: "nodes", id: prevId }, { selected: false });
      } catch {
        /* ignore */
      }
    }
    const newId = selectedNode?.id ?? null;
    if (newId != null && newId !== "") {
      try {
        map.setFeatureState({ source: "nodes", id: newId }, { selected: true });
      } catch {
        /* ignore */
      }
    }
    selectedNodeIdRef.current = newId;
  }, [selectedNode, mapReady, nodesLoaded]);

  // Resize map when sidebar content changes (esp. phase transitions)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const id = window.setTimeout(() => {
      try {
        map.resize();
      } catch {
        /* ignore */
      }
    }, 80);
    return () => window.clearTimeout(id);
  }, [phase, selectedNode]);

  const handleClosePanel = useCallback(() => setSelectedNode(null), []);

  const handleCopyNodeId = useCallback((nid: string) => {
    if (!nid) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(nid).then(
        () => toast.success(`Node ID copie : ${nid}`),
        () => toast.error("Copie impossible"),
      );
    } else {
      toast.error("Clipboard indisponible");
    }
  }, []);

  const toggleCause = useCallback((c: CauseKey) => {
    setActiveCauses((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  }, []);

  const toggleTopo = useCallback((t: TopologyKey) => {
    setActiveTopos((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }, []);

  const handleSearchSubmit = useCallback(() => {
    const map = mapRef.current;
    const data = nodesDataRef.current;
    if (!map || !data || !searchValue.trim()) return;
    const needle = searchValue.trim();
    const match = data.features.find((f) =>
      String(f.properties?.node_id ?? "").includes(needle),
    );
    if (!match) {
      setSearchHint(`Aucun noeud avec node_id contenant "${needle}".`);
      return;
    }
    const g = match.geometry as GeoJSON.Geometry;
    if (g.type !== "Point") return;
    const c = g.coordinates as number[];
    const coords: [number, number] = [Number(c[0]), Number(c[1])];
    setSearchHint(`Noeud ${match.properties?.node_id} centre.`);

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    map.flyTo({
      center: coords,
      zoom: 16,
      duration: reduced ? 0 : 1000,
      essential: true,
    });
    const props = (match.properties ?? {}) as Record<string, unknown>;
    const fid =
      match.id != null
        ? (match.id as string | number)
        : (props.node_id as string | number | undefined) ?? "";
    setTimeout(
      () => {
        setSelectedNode({ id: fid, coords, properties: props });
      },
      reduced ? 0 : 1050,
    );
  }, [searchValue]);

  const handleFitVisible = useCallback(() => {
    const map = mapRef.current;
    const data = nodesDataRef.current;
    if (!map || !data) return;
    let minLng = Infinity,
      minLat = Infinity,
      maxLng = -Infinity,
      maxLat = -Infinity,
      any = false;
    const needle = searchValue.trim();
    data.features.forEach((f) => {
      const p = f.properties as Record<string, unknown>;
      if (!activeCauses.has(p.principal_cause as CauseKey)) return;
      if (!activeTopos.has(p.topology as TopologyKey)) return;
      if (currentTier !== "all" && p.tier !== currentTier) return;
      if (needle && !String(p.node_id).includes(needle)) return;
      const g = f.geometry as GeoJSON.Geometry;
      if (g.type !== "Point") return;
      const c = g.coordinates as number[];
      const lng = Number(c[0]);
      const lat = Number(c[1]);
      if (!isFinite(lng) || !isFinite(lat)) return;
      any = true;
      if (lng < minLng) minLng = lng;
      if (lat < minLat) minLat = lat;
      if (lng > maxLng) maxLng = lng;
      if (lat > maxLat) maxLat = lat;
    });
    if (any) {
      const reduced =
        typeof window !== "undefined" &&
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      map.fitBounds(
        [
          [minLng, minLat],
          [maxLng, maxLat],
        ],
        { padding: 60, duration: reduced ? 0 : 800, maxZoom: 15 },
      );
    } else {
      toast.message("Aucun noeud visible avec ces filtres.");
    }
  }, [activeCauses, activeTopos, currentTier, searchValue]);

  const handleReset = useCallback(() => {
    setActiveCauses(new Set(CAUSE_ORDER));
    setActiveTopos(new Set(TOPO_ORDER));
    setCurrentTier("all");
    setSearchValue("");
    setSearchHint(null);
    const map = mapRef.current;
    if (map) {
      const reduced =
        typeof window !== "undefined" &&
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      map.flyTo({
        center: LYON_CENTER,
        zoom: LYON_ZOOM,
        duration: reduced ? 0 : 800,
      });
    }
  }, []);

  // --- Render -----------------------------------------------------------

  if (!hydrated) {
    return (
      <div
        className="flex items-center justify-center min-h-screen"
        style={{ background: "#0d1117", color: "#e6edf3" }}
      >
        <Loader2 className="animate-spin text-[#FFB000]" size={24} />
      </div>
    );
  }

  const canAnalyze = !!geoUploadResp && !geoUploading && !fcdUploading;
  const fcdDegraded = analyzeResp?.fcd_joined === false;
  const fcdWarning = analyzeResp?.warning ?? null;

  // KPI : la cause/topo la + suspecte = celle avec le plus de noeuds
  const dominantCause = (() => {
    let best: { c: string; n: number } = { c: "—", n: 0 };
    for (const c of CAUSE_ORDER) {
      const n = causeCounts[c] ?? 0;
      if (n > best.n) best = { c: CAUSE_LABELS_FR[c] || c, n };
    }
    return best;
  })();

  const pct = (n: number) =>
    totalNodes > 0 ? ((n / totalNodes) * 100).toFixed(1) : "0";

  return (
    <div
      ref={rootRef}
      className="flex flex-col min-h-[calc(100vh-3rem)]"
      style={{ background: "#0d1117", color: "#e6edf3" }}
    >
      {/* Header */}
      <header
        className="sticky top-0 z-30 border-b border-[#1f2740] bg-[rgba(13,17,23,.92)] backdrop-blur"
        role="banner"
      >
        <div className="max-w-[1600px] mx-auto px-4 py-3 flex items-center gap-4">
          <button
            type="button"
            onClick={() => router.push("/")}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[#a0b0d8] hover:text-[#e6edf3] hover:bg-[rgba(255,255,255,.05)] transition-colors text-xs font-medium cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFB000]"
            aria-label="Retour a l'accueil"
          >
            <ArrowLeft size={14} />
            <span>Retour</span>
          </button>
          <div className="hidden sm:block w-px h-5 bg-[#1f2740]" aria-hidden />
          <div className="flex items-center gap-2 min-w-0">
            <AlertCircle size={16} className="text-[#FFB000] shrink-0" />
            {/* Titre en amber (#FFB000) : couleur accent du projet, coherent
                avec /visualisation et lisible sur fonds clairs en overlay. */}
            <h1 className="text-sm font-semibold text-[#FFB000] truncate">
              Analyse discontinuites JOr+DPL
            </h1>
          </div>
          {phase === "ready" && geoUploadResp && (
            <div className="ml-auto flex items-center gap-2 text-[11px] text-[#a0b0d8] font-mono">
              <span className="hidden md:inline">
                session {geoUploadResp.session_id.slice(0, 8)}
              </span>
            </div>
          )}
        </div>
      </header>

      {/* Bandeau "Mode degrade" si phase ready et pas de jointure FCD */}
      {phase === "ready" && fcdDegraded && (
        <div
          className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 flex items-start gap-2 text-[11.5px] text-amber-100"
          role="status"
          aria-live="polite"
        >
          <AlertTriangle
            size={14}
            className="text-amber-300 shrink-0 mt-0.5"
            aria-hidden
          />
          <div className="min-w-0">
            <span className="inline-block mr-2 px-1.5 py-[1px] rounded bg-amber-500/20 text-amber-200 font-semibold uppercase tracking-wide text-[10px]">
              Mode degrade : 4 causes sur 8
            </span>
            <span className="text-amber-100/90">
              {fcdWarning ??
                "Inputs FCD non joints — les classifications FCD_TV_cliff et FCD_PL_cliff ne peuvent pas se declencher. Uploadez FCDREFGLOBAL_2025.parquet pour la classification complete."}
            </span>
          </div>
        </div>
      )}

      {/* KPIs (uniquement en phase ready) — UX5 : stagger reveal des cards */}
      {phase === "ready" && (
        <section
          className="border-b border-[#1f2740] bg-[rgba(15,20,36,.4)]"
          aria-label="Indicateurs cle"
        >
          <RevealOnScroll
            variant="slide-up"
            stagger={0.06}
            distance={12}
            className="max-w-[1600px] mx-auto px-4 py-3 grid grid-cols-2 md:grid-cols-4 gap-3"
          >
            <KpiCard
              label="Noeuds discontinus"
              value={fmtFR(totalNodes)}
              hint={
                visibleNodes !== totalNodes
                  ? `${fmtFR(visibleNodes)} visibles`
                  : analyzeResp?.pipeline_duration_s
                    ? `pipeline ${fmtFRdec(analyzeResp.pipeline_duration_s, 1)} s`
                    : undefined
              }
              accentColor="#FFB000"
            />
            <KpiCard
              label="Bretelle"
              value={`${pct(topoCounts["Bretelle"] ?? 0)} %`}
              hint={`${fmtFR(topoCounts["Bretelle"] ?? 0)} noeuds`}
              accentColor={TOPO_PALETTE.Bretelle}
            />
            <KpiCard
              label="Carrefour"
              value={`${pct(topoCounts["Carrefour"] ?? 0)} %`}
              hint={`${fmtFR(topoCounts["Carrefour"] ?? 0)} noeuds`}
              accentColor={TOPO_PALETTE.Carrefour}
            />
            <KpiCard
              label="Continuite (suspect)"
              value={`${pct(topoCounts["Continuite"] ?? 0)} %`}
              hint={`${fmtFR(topoCounts["Continuite"] ?? 0)} noeuds · cause #1 : ${dominantCause.c}`}
              accentColor={TOPO_PALETTE.Continuite}
            />
          </RevealOnScroll>
        </section>
      )}

      {/* Bandeau + Map unifie */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0">
        <aside
          ref={asideRef}
          // NIT 2 : sticky sur grand ecran (top-12 = hauteur header). L'overflow
          // interne reste actif (sidebar scrollable independamment).
          className="w-full lg:w-[380px] lg:shrink-0 lg:sticky lg:top-12 lg:self-start border-r border-[#1f2740] bg-[rgba(15,20,36,.94)] px-4 py-4 space-y-4 overflow-y-auto"
          aria-label={
            phase === "ready"
              ? "Panneaux statistiques et filtres"
              : "Chargement des donnees"
          }
          style={{ maxHeight: phase === "ready" ? "calc(100vh - 9rem)" : undefined }}
        >
          {phase === "upload" && (
            <UploadBandeau
              geoFile={geoFile}
              fcdFile={fcdFile}
              geoUploading={geoUploading}
              fcdUploading={fcdUploading}
              geoUploadResp={geoUploadResp}
              fcdUploadResp={fcdUploadResp}
              error={error}
              canAnalyze={canAnalyze}
              onUploadGeo={handleUploadGeo}
              onClearGeo={handleClearGeo}
              onUploadFcd={handleUploadFcd}
              onClearFcd={handleClearFcd}
              onAnalyze={handleAnalyze}
            />
          )}

          {phase === "analyzing" && <AnalyzingBandeau />}

          {phase === "ready" && (
            <ReadySidebar
              totalNodes={totalNodes}
              visibleNodes={visibleNodes}
              causeCounts={causeCounts}
              topoCounts={topoCounts}
              activeCauses={activeCauses}
              activeTopos={activeTopos}
              currentTier={currentTier}
              searchValue={searchValue}
              searchHint={searchHint}
              onToggleCause={toggleCause}
              onToggleTopo={toggleTopo}
              onTierChange={setCurrentTier}
              onSearchChange={(v) => {
                setSearchValue(v);
                setSearchHint(null);
              }}
              onSearchSubmit={handleSearchSubmit}
              onFitVisible={handleFitVisible}
              onReset={handleReset}
            />
          )}
        </aside>

        {/* Map (single instance) — NIT 1 : <section> au lieu de <main> pour
            eviter le double <main> avec le root layout. */}
        <section
          ref={mapWrapperRef}
          role="region"
          className="flex-1 relative min-h-[480px] lg:min-h-0 min-w-0"
          aria-label="Carte interactive"
          style={{ background: "#0d1117" }}
        >
          {phase !== "ready" && (
            <div
              className="absolute top-3 left-1/2 -translate-x-1/2 z-10 pointer-events-none"
              role="status"
              aria-live="polite"
            >
              {/* UX5 : badge ShimmerText gold + NeonBorder amber qui pulse
                  un peu plus vite quand analyse en cours (signal d'activite). */}
              <NeonBorder
                tone="amber"
                speed={phase === "analyzing" ? 1.8 : 3.4}
                rotate={false}
                className="rounded-full"
              >
                <div className="px-3 py-1.5 rounded-full flex items-center gap-2">
                  <Eye size={12} aria-hidden className="text-[#FFB000]" />
                  <ShimmerText variant="neon-white" className="text-xs">
                    {phase === "analyzing"
                      ? "Apercu Lyon — analyse en cours, patiente quelques secondes"
                      : "Apercu Lyon — depose tes donnees pour passer en mode reel"}
                  </ShimmerText>
                </div>
              </NeonBorder>
            </div>
          )}
          <div
            ref={mapContainerRef}
            className="absolute inset-0"
            style={{ position: "absolute", inset: 0 }}
          />
          {/* Switcher de fond de carte (top-right, sous les controles MapLibre).
              NB cursor : sur la map preview (phase != ready), le curseur "grab"
              reste actif pour encourager l'exploration libre de Lyon. Les
              features data ne sont pas hover-interactives en preview, donc on
              ne neutralise pas le pan/zoom du canvas. */}
          <BasemapSwitcher mapRef={mapRef} />
        </section>

        {/* Side panel pour le noeud selectionne */}
        {phase === "ready" && selectedNode && (
          <aside
            className="w-full lg:w-[380px] lg:shrink-0 border-l border-[#1f2740] bg-[#1B1F23] overflow-y-auto flex flex-col"
            style={{ maxHeight: "calc(100vh - 9rem)" }}
            aria-label="Détail du nœud sélectionné"
          >
            <NodePanel
              feature={selectedNode}
              onClose={handleClosePanel}
              onCopyNodeId={handleCopyNodeId}
            />
          </aside>
        )}
      </div>
    </div>
  );
}

// ===========================================================================
// Bandeau gauche : upload
// ===========================================================================

function UploadBandeau({
  geoFile,
  fcdFile,
  geoUploading,
  fcdUploading,
  geoUploadResp,
  fcdUploadResp,
  error,
  canAnalyze,
  onUploadGeo,
  onClearGeo,
  onUploadFcd,
  onClearFcd,
  onAnalyze,
}: {
  geoFile: File | null;
  fcdFile: File | null;
  geoUploading: boolean;
  fcdUploading: boolean;
  geoUploadResp: UploadGeojsonResponse | null;
  fcdUploadResp: UploadFcdResponse | null;
  error: string | null;
  canAnalyze: boolean;
  onUploadGeo: (f: File) => void;
  onClearGeo: () => void;
  onUploadFcd: (f: File) => void;
  onClearFcd: () => void;
  onAnalyze: () => void;
}) {
  const successRef = useRef<HTMLDivElement | null>(null);

  useGSAP(() => {
    if (!successRef.current) return;
    gsap.fromTo(
      successRef.current,
      { scale: 0.92, autoAlpha: 0 },
      { scale: 1, autoAlpha: 1, duration: 0.4, ease: "back.out(1.6)" },
    );
  }, { dependencies: [!!geoUploadResp] });

  return (
    <div className="space-y-4">
      {/* Sam intro */}
      <div className="rounded-xl border border-[#FFB000]/20 bg-gradient-to-br from-[rgba(255,176,0,.06)] to-transparent p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-[#FFB000] shrink-0" />
          <h2 className="text-sm font-semibold text-[#e6edf3]">
            Charge ton reseau enrichi
          </h2>
        </div>
        <p className="text-[12px] text-[#a0b0d8] leading-relaxed">
          GeoJSON de segments enrichi avec JOr et DPL (obligatoire) + parquet
          FCD (optionnel, mais recommande). Pipeline 5 etapes : adjacency
          network, filtrage user-rule (2 000 / 4 000 v/j), driver ranking,
          classification topologique, cause principale. <strong>~30 s a 2
          min</strong> selon le volume.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-2 text-[11.5px] text-amber-200">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Zone 1 : GeoJSON enrichi */}
      <div className="rounded-xl border border-[#1f2740] bg-[rgba(13,17,23,.5)] p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-[rgba(255,176,0,0.12)] flex items-center justify-center text-[#FFB000]">
            <AlertCircle size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[13px] font-semibold text-[#e6edf3] leading-tight">
              GeoJSON segments
            </h3>
            <p className="text-[10.5px] text-[#a0b0d8] leading-tight mt-0.5">
              .geojson, .json ou .parquet — sortie module Carte ou HERE 2025
            </p>
          </div>
          {geoUploadResp && (
            <CheckCircle2
              size={16}
              className="text-emerald-400 shrink-0"
              aria-label="Upload reussi"
            />
          )}
        </div>
        <DropZone
          file={geoFile}
          onFile={onUploadGeo}
          onClear={onClearGeo}
          accept={{
            "application/geo+json": [".geojson"],
            "application/json": [".json"],
            "application/octet-stream": [".parquet"],
          }}
          label="Depose le GeoJSON enrichi"
          description=".geojson, .json ou .parquet"
        />
        {geoUploading && (
          <div className="flex items-center gap-2 text-[11px] text-[#a0b0d8]">
            <Loader2 size={12} className="animate-spin text-[#FFB000]" />
            <span>Upload en cours...</span>
          </div>
        )}
        {geoUploadResp && (
          <div
            ref={successRef}
            className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-1 text-[11px] text-emerald-200"
          >
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">Features</span>
              <span className="font-mono tabular-nums">
                {NF_FR.format(geoUploadResp.n_features)}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">Poids</span>
              <span className="font-mono tabular-nums">
                {geoUploadResp.file_size_mb.toFixed(2)} MB
              </span>
            </div>
            {geoUploadResp.columns && (
              <div className="flex justify-between gap-3">
                <span className="text-[#a0b0d8]">Colonnes</span>
                <span className="font-mono tabular-nums">
                  {geoUploadResp.columns.length}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Zone 2 : Parquet FCD */}
      <div className="rounded-xl border border-[#1f2740] bg-[rgba(13,17,23,.5)] p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-[rgba(55,126,184,0.18)] flex items-center justify-center text-[#377EB8]">
            <AlertCircle size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <h3 className="text-[13px] font-semibold text-[#e6edf3] leading-tight">
                Donnees FCD
              </h3>
              <span
                className="inline-flex items-center px-1.5 py-[1px] rounded text-[9px] font-semibold uppercase tracking-wide bg-[rgba(255,255,255,.06)] text-[#a0b0d8] border border-[#1f2740]"
                aria-label="Champ optionnel"
              >
                Recommande
              </span>
            </div>
            <p className="text-[10.5px] text-[#a0b0d8] leading-tight mt-0.5">
              FCDREFGLOBAL_2025.parquet pour activer les classifications
              FCD_TV_cliff / FCD_PL_cliff.
            </p>
          </div>
          {fcdUploadResp && (
            <CheckCircle2
              size={16}
              className="text-emerald-400 shrink-0"
              aria-label="Upload reussi"
            />
          )}
        </div>
        <DropZone
          file={fcdFile}
          onFile={onUploadFcd}
          onClear={onClearFcd}
          accept={{
            "application/octet-stream": [".parquet"],
            "application/x-parquet": [".parquet"],
          }}
          label="Depose le parquet FCD"
          description=".parquet"
        />
        {!geoUploadResp && (
          <p className="text-[10px] text-[#7d8aa8] leading-snug">
            Uploadez d&apos;abord le GeoJSON ci-dessus avant le parquet FCD.
          </p>
        )}
        {fcdUploading && (
          <div className="flex items-center gap-2 text-[11px] text-[#a0b0d8]">
            <Loader2 size={12} className="animate-spin text-[#377EB8]" />
            <span>Upload FCD en cours...</span>
          </div>
        )}
        {fcdUploadResp && (
          <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 space-y-1 text-[11px] text-sky-200">
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">Segments</span>
              <span className="font-mono tabular-nums">
                {NF_FR.format(fcdUploadResp.n_segments)}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">Poids</span>
              <span className="font-mono tabular-nums">
                {fcdUploadResp.file_size_mb.toFixed(2)} MB
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">Colonnes joignables</span>
              <span className="font-mono tabular-nums">
                {fcdUploadResp.columns_detected.length}
              </span>
            </div>
            {fcdUploadResp.columns_detected.length > 0 && (
              <div className="text-[10px] text-[#a0b0d8] mt-1 font-mono break-words">
                {fcdUploadResp.columns_detected.join(", ")}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action button (sticky bottom) — UX5 : MagneticButton amber +
          NeonBorder pulse quand canAnalyze, idiome "ready to fire". */}
      <div className="sticky bottom-0 -mx-4 px-4 pb-3 pt-3 bg-gradient-to-t from-[rgba(15,20,36,.98)] via-[rgba(15,20,36,.92)] to-transparent">
        {canAnalyze ? (
          <NeonBorder tone="amber" speed={2.6} className="rounded-md">
            <MagneticButton
              variant="primary"
              size="md"
              onClick={onAnalyze}
              className="w-full bg-[#FFB000] !text-[#1A1300] hover:bg-[#FFC233] border-[#FFB000]"
            >
              <Upload size={16} />
              Lancer l&apos;analyse
            </MagneticButton>
          </NeonBorder>
        ) : (
          <button
            type="button"
            disabled
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-[rgba(255,255,255,.05)] text-[#7d8aa8] cursor-not-allowed"
          >
            <Upload size={16} />
            Lancer l&apos;analyse
          </button>
        )}
        <p className="text-[10px] text-[#7d8aa8] mt-1.5 text-center">
          Pipeline ~1 min sur 100k segments — long-running mais deterministe.
        </p>
      </div>
    </div>
  );
}

// ===========================================================================
// Bandeau gauche : analyzing (remplace le bouton + desactive les dropzones)
// ===========================================================================

function AnalyzingBandeau() {
  const barRef = useRef<HTMLDivElement | null>(null);

  useGSAP(() => {
    if (!barRef.current) return;
    gsap.fromTo(
      barRef.current,
      { width: "10%" },
      {
        width: "75%",
        duration: 2.4,
        ease: "power2.out",
        repeat: -1,
        yoyo: true,
      },
    );
  }, { dependencies: [] });

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[#FFB000]/30 bg-gradient-to-br from-[rgba(255,176,0,.08)] to-transparent p-5 text-center space-y-3">
        <div className="mx-auto w-12 h-12 rounded-full bg-[rgba(255,176,0,0.12)] flex items-center justify-center text-[#FFB000]">
          <Loader2 size={24} className="animate-spin" />
        </div>
        <div className="space-y-1">
          <h2 className="text-sm font-semibold text-[#e6edf3]">
            Analyse en cours...
          </h2>
          <p className="text-[11px] text-[#a0b0d8] leading-relaxed">
            5 etapes : adjacency network, filtrage user-rule, driver ranking,
            classification topologique, cause principale.
          </p>
          <p className="text-[10px] text-[#7d8aa8]">
            ~1 a 2 minutes pour 100k+ segments.
          </p>
        </div>
        <div className="h-1.5 w-full bg-[#1f2740] rounded-full overflow-hidden">
          <div
            ref={barRef}
            className="h-full bg-gradient-to-r from-[#FFB000] to-[#FF7F00]"
            style={{ width: "10%" }}
          />
        </div>
      </div>

      {/* Dropzones desactivees visuellement pendant l'analyse */}
      <div className="rounded-xl border border-[#1f2740] bg-[rgba(13,17,23,.3)] p-4 space-y-2 opacity-50 pointer-events-none">
        <p className="text-[11px] text-[#a0b0d8]">
          Les uploads sont desactives pendant l&apos;analyse.
        </p>
      </div>
    </div>
  );
}

// ===========================================================================
// Bandeau gauche : ready (filtres + causes + topologie)
// ===========================================================================

function ReadySidebar({
  totalNodes,
  visibleNodes,
  causeCounts,
  topoCounts,
  activeCauses,
  activeTopos,
  currentTier,
  searchValue,
  searchHint,
  onToggleCause,
  onToggleTopo,
  onTierChange,
  onSearchChange,
  onSearchSubmit,
  onFitVisible,
  onReset,
}: {
  totalNodes: number;
  visibleNodes: number;
  causeCounts: Record<string, number>;
  topoCounts: Record<string, number>;
  activeCauses: Set<CauseKey>;
  activeTopos: Set<TopologyKey>;
  currentTier: "all" | "orange" | "red";
  searchValue: string;
  searchHint: string | null;
  onToggleCause: (c: CauseKey) => void;
  onToggleTopo: (t: TopologyKey) => void;
  onTierChange: (t: "all" | "orange" | "red") => void;
  onSearchChange: (v: string) => void;
  onSearchSubmit: () => void;
  onFitVisible: () => void;
  onReset: () => void;
}) {
  const pct = (n: number) =>
    totalNodes > 0 ? ((n / totalNodes) * 100).toFixed(1) : "0";

  return (
    <>
      {/* Panel A — Causes */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
            Causes principales
          </h4>
          <span className="text-[10px] text-[#7d8aa8] font-mono tabular-nums">
            {fmtFR(visibleNodes)} / {fmtFR(totalNodes)}
          </span>
        </div>
        <div
          className="flex h-2 rounded overflow-hidden bg-[#1f2740]"
          role="img"
          aria-label="Repartition des causes"
        >
          {CAUSE_ORDER.map((c) => {
            const n = causeCounts[c] ?? 0;
            if (n === 0 || totalNodes === 0) return null;
            const width = ((n / totalNodes) * 100).toFixed(2);
            return (
              <div
                key={c}
                style={{ background: PALETTE[c], width: `${width}%` }}
                title={`${CAUSE_LABELS_FR[c]} : ${fmtFR(n)}`}
              />
            );
          })}
        </div>
        <div className="space-y-0.5">
          {CAUSE_ORDER.map((c) => {
            const n = causeCounts[c] ?? 0;
            if (n === 0) return null;
            return (
              <CauseCard
                key={c}
                label={CAUSE_LABELS_FR[c]}
                count={n}
                pct={pct(n)}
                color={PALETTE[c]}
                active={activeCauses.has(c)}
                onToggle={() => onToggleCause(c)}
                variant="fill"
              />
            );
          })}
        </div>
      </div>

      {/* Panel B — Topologie */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
          Topologie
        </h4>
        <div
          className="flex h-2 rounded overflow-hidden bg-[#1f2740]"
          role="img"
          aria-label="Repartition par topologie"
        >
          {TOPO_ORDER.map((t) => {
            const n = topoCounts[t] ?? 0;
            if (n === 0 || totalNodes === 0) return null;
            const width = ((n / totalNodes) * 100).toFixed(2);
            return (
              <div
                key={t}
                style={{ background: TOPO_PALETTE[t], width: `${width}%` }}
                title={`${TOPO_LABELS_FR[t]} : ${fmtFR(n)}`}
              />
            );
          })}
        </div>
        <div className="space-y-0.5">
          {TOPO_ORDER.map((t) => {
            const n = topoCounts[t] ?? 0;
            if (n === 0) return null;
            return (
              <CauseCard
                key={t}
                label={TOPO_LABELS_FR[t]}
                count={n}
                pct={pct(n)}
                color={TOPO_PALETTE[t]}
                active={activeTopos.has(t)}
                onToggle={() => onToggleTopo(t)}
                variant="outline"
              />
            );
          })}
        </div>
        <div className="text-[10.5px] text-[#a0b0d8] leading-relaxed bg-[#14171A] p-2 rounded border-l-2 border-[#FFB000] mt-2">
          Une discontinuite sur un noeud{" "}
          <strong className="text-[#FFA07A]">
            « Continuite segment »
          </strong>{" "}
          est plus suspecte qu&apos;un saut a un carrefour ou en sortie de
          bretelle : il n&apos;y a aucune intersection physique pour la
          justifier.
        </div>
      </div>

      {/* Tier filter */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
          Severite
        </h4>
        <div className="flex gap-1">
          {(["all", "orange", "red"] as const).map((t) => {
            const active = currentTier === t;
            const label =
              t === "all" ? "Tous" : t === "orange" ? "Orange" : "Rouge";
            return (
              <button
                key={t}
                type="button"
                onClick={() => onTierChange(t)}
                className={cn(
                  "flex-1 px-2 py-1.5 rounded text-[10px] uppercase tracking-wide font-semibold transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFB000]",
                  active
                    ? "bg-[rgba(255,176,0,0.15)] text-[#FFB000] border border-[#FFB000]"
                    : "bg-[#14171A] text-[#a0b0d8] border border-[#1f2740] hover:text-[#e6edf3]",
                )}
                aria-pressed={active}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Search */}
      <div className="rounded-lg border border-[#1f2740] bg-[rgba(13,17,23,.6)] p-3 space-y-2">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#e6edf3]">
          Recherche
        </h4>
        <div className="flex gap-1.5">
          <input
            type="search"
            value={searchValue}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSearchSubmit();
            }}
            placeholder="node_id"
            className="flex-1 px-2 py-1.5 rounded text-xs bg-[#14171A] border border-[#1f2740] text-[#e6edf3] focus:outline-none focus:border-[#FFB000]"
            autoComplete="off"
          />
          <button
            type="button"
            onClick={onSearchSubmit}
            className="px-2.5 py-1.5 rounded bg-[#1f2740] text-[#FFB000] hover:bg-[#2a3550] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFB000]"
            aria-label="Rechercher un node_id"
          >
            <Search size={14} />
          </button>
        </div>
        {searchHint && (
          <p className="text-[10px] text-[#a0b0d8]">{searchHint}</p>
        )}
      </div>

      {/* Actions */}
      <div className="space-y-1.5">
        <button
          type="button"
          onClick={onFitVisible}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-xs font-semibold bg-[#FFB000] text-[#1A1300] hover:bg-[#FFC233] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFB000]"
        >
          <Crosshair size={14} />
          Centrer sur les noeuds
        </button>
        <button
          type="button"
          onClick={onReset}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-xs bg-[#14171A] text-[#a0b0d8] border border-[#1f2740] hover:text-[#e6edf3] hover:bg-[#20252B] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFB000]"
        >
          <RotateCcw size={14} />
          Reinitialiser les filtres
        </button>
      </div>

      <div className="pt-3 mt-2 border-t border-[#1f2740] text-[10px] text-[#7d8aa8] leading-relaxed">
        Encodage marker : <strong>remplissage</strong> = cause principale,{" "}
        <strong>contour</strong> = topologie. Fond CartoDB Positron.
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Bbox helper (fallback si backend ne renvoie pas la bbox)
// ---------------------------------------------------------------------------

function computeBboxFromFeatures(
  data: GeoJSON.FeatureCollection,
): [number, number, number, number] | null {
  let minLng = Infinity,
    minLat = Infinity,
    maxLng = -Infinity,
    maxLat = -Infinity,
    any = false;
  for (const f of data.features) {
    const g = f.geometry as GeoJSON.Geometry;
    if (g.type !== "Point") continue;
    const c = g.coordinates as number[];
    const lng = Number(c[0]);
    const lat = Number(c[1]);
    if (!isFinite(lng) || !isFinite(lat)) continue;
    any = true;
    if (lng < minLng) minLng = lng;
    if (lat < minLat) minLat = lat;
    if (lng > maxLng) maxLng = lng;
    if (lat > maxLat) maxLat = lat;
  }
  return any ? [minLng, minLat, maxLng, maxLat] : null;
}
