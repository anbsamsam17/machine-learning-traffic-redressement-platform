"use client";

/**
 * Visualisation Carte + Capteurs — module independant de la pipeline.
 *
 * UX unifie (refonte 2026-05) :
 *  - Bandeau gauche TOUJOURS visible (sticky, ~380px) :
 *      * Avant upload : Sam intro + 2 dropzones + bouton "Voir mes donnees".
 *      * Apres upload : panneau filtres / couches / search / legende editable.
 *  - Carte droite TOUJOURS visible :
 *      * Avant upload : preview Lyon (interactions desactivees).
 *      * Apres upload : donnees reelles, popup + hover + selection.
 *  - Crossfade GSAP entre preview et donnees reelles. Une seule instance
 *    MapLibre est utilisee (mapRef partage).
 *
 * Endpoints backend consommes (cf. apps/api/app/routers/visualisation.py) :
 *  - POST /api/visualisation/upload-geojson  (multipart: file [+ session_id])
 *  - POST /api/visualisation/upload-sensors  (multipart: file + session_id)
 *  - GET  /api/visualisation/geojson/{sid}   (stream application/geo+json)
 *  - GET  /api/visualisation/sensors/{sid}
 *
 * Carte : MapLibre GL JS, basemap Carto Dark Matter, centre Lyon (45.75, 4.85),
 * zoom 11. Layers segments-tvr / segments-dpl / sensors-tv / sensors-pl avec
 * paint expressions dependant de TVr/DPL.
 *
 * Refonte structurelle (2026-05) :
 *  - UploadBandeau : reste inline (composant page-specific, non reutilise).
 *  - ActiveSidebar -> @/components/visualisation/ActiveSidebar (extrait).
 *  - Popup HTML  -> @/lib/visualisation/popup-html (segment + sensor).
 *  - KPIs calc   -> @/lib/visualisation/kpi (median + computeKpis).
 *  - Sensors layers -> @/lib/map/setup (installSensorLayers).
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Loader2,
  AlertTriangle,
  Layers as LayersIcon,
  Car,
  Truck,
  X,
  Activity,
  Eye,
  CheckCircle2,
  Sparkles,
  Sunrise,
  Sunset,
  MapPinned,
} from "lucide-react";
import { toast } from "sonner";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";

import { DropZone } from "@/components/upload/drop-zone";
import { BasemapSwitcher } from "@/components/map/BasemapSwitcher";
import {
  TVR_PALETTE_NEON,
  DPL_PALETTE_NEON,
  addNeonLineLayers,
  updateNeonLineColor,
  setNeonLineFilter,
  setNeonLineVisibility,
  removeNeonLineLayers,
  setNeonLineOpacity,
  bidirOffsetExpr,
  type Stop,
} from "@/lib/map/palette";
import { disambiguateFTClick } from "@/lib/map/ft-disambiguate";
import { installSensorLayers } from "@/lib/map/setup";
import { apiClient, ApiError } from "@/lib/api";
import { getApiBase } from "@/lib/api-url";
import { getToken } from "@/lib/auth";
import { samNotify } from "@/lib/sam-fallback";
import { cn } from "@/lib/utils";
import { useMapInstance } from "@/lib/hooks/use-map-instance";
import {
  ActiveSidebar,
  type Mode,
} from "@/components/visualisation/ActiveSidebar";
import {
  segmentPopupHtml,
  sensorPopupHtml,
} from "@/components/visualisation/SegmentPopupContent";
import { POPUP_CSS } from "@/lib/visualisation/popup-html";
import {
  computeKpis,
  EMPTY_KPIS,
  type VisualisationKpis,
} from "@/lib/visualisation/kpi";
// UX5 — composants premium pour CTA upload + KPI bar
import {
  MagneticButton,
  ShimmerText,
  NeonBorder,
  RevealOnScroll,
} from "@/components/ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GeojsonUploadResponse {
  session_id: string;
  filename: string;
  n_features: number;
  bbox: [number, number, number, number] | null;
  file_size_mb: number;
  columns: string[];
}

interface SensorsUploadResponse {
  session_id: string;
  filename: string;
  n_sensors: number;
  n_tv: number;
  n_pl: number;
  bbox: [number, number, number, number] | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LYON_CENTER: [number, number] = [4.85, 45.75];
const LYON_ZOOM = 11;
const NF_FR = new Intl.NumberFormat("fr-FR");

// Palettes "neon" partagees (TVr chaude / DPL froide). Le type Stop, les
// stops par defaut et l'expression `step` viennent de @/lib/map/palette pour
// rester synchronises avec la page /discontinuites et le helper de couches
// neon (halo + core + shine).
const TVR_STOPS_DEFAULT: Stop[] = TVR_PALETTE_NEON;
const DPL_STOPS_DEFAULT: Stop[] = DPL_PALETTE_NEON;

// Heuristique perf : on desactive la couche "shine" (3eme passe blanche) si
// le dataset depasse ce seuil. 50k features = limite empirique au-dela de
// laquelle 3 layers ligne par mode font chuter le FPS sous 30 (laptop iGPU).
const NEON_SHINE_MAX_FEATURES = 50_000;

// Fond de carte par defaut : Satellite (Esri World Imagery), pour maximiser le
// contraste des segments neon. Le composant <BasemapSwitcher /> permet de
// basculer vers Voyager/Positron/Dark Matter ; la preference est persistee
// dans localStorage. Constantes URL+attribution dans lib/map/basemaps.ts.

const MONO = `ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace`;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(v: number | null | undefined, unit?: string): string {
  if (v == null || !isFinite(v)) return "—";
  const out = NF_FR.format(Math.round(v));
  return unit ? `${out} ${unit}` : out;
}

function midPoint(coords: number[][] | undefined): [number, number] | null {
  if (!coords || coords.length === 0) return null;
  const mid = coords[Math.floor(coords.length / 2)];
  if (!mid || mid.length < 2) return null;
  return [Number(mid[0]), Number(mid[1])];
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
    <div className="rounded-lg border border-[#1f2740] bg-[rgba(15,20,36,.6)] p-3 flex items-start gap-3">
      <div className="shrink-0 w-8 h-8 rounded bg-[rgba(34,211,238,.1)] flex items-center justify-center text-[#22d3ee] [&_svg]:size-4">
        {icon}
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

export default function VisualisationPage() {
  const router = useRouter();

  // --- Upload state -------------------------------------------------------
  const [geoFile, setGeoFile] = useState<File | null>(null);
  const [sensorFile, setSensorFile] = useState<File | null>(null);
  const [geoUploading, setGeoUploading] = useState(false);
  const [sensorUploading, setSensorUploading] = useState(false);
  const [geoUploadResp, setGeoUploadResp] = useState<GeojsonUploadResponse | null>(null);
  const [sensorUploadResp, setSensorUploadResp] = useState<SensorsUploadResponse | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // active = donnees reelles affichees (post-upload). Tant que false, le map
  // reste en preview mode. Bascule via le bouton "Voir mes donnees".
  const [active, setActive] = useState(false);

  // --- Map state ----------------------------------------------------------
  // UNE SEULE instance MapLibre, partagee preview/active. On swap juste les
  // sources et layers via les helpers add/remove ci-dessous.
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const hoveredIdRef = useRef<string | number | null>(null);
  const segmentsDataRef = useRef<GeoJSON.FeatureCollection | null>(null);
  const sensorsDataRef = useRef<GeoJSON.FeatureCollection | null>(null);
  const previewLoadedRef = useRef(false);
  const realLayersInstalledRef = useRef(false);

  // Hook MapLibre partage (cf. /lib/hooks/use-map-instance). Une seule
  // instance, NavigationControl en top-right + ScaleControl en bottom-left
  // (positions historiques). Le CSS popup est injecte une fois quand la map
  // devient prete.
  const { map: mapInstance, ready: mapReady } = useMapInstance({
    containerRef: mapContainerRef,
    center: LYON_CENTER,
    zoom: LYON_ZOOM,
    devGlobalName: "__map",
    onReady: () => {
      if (
        typeof document !== "undefined" &&
        !document.getElementById("visualisation-popup-css")
      ) {
        const styleEl = document.createElement("style");
        styleEl.id = "visualisation-popup-css";
        styleEl.textContent = POPUP_CSS;
        document.head.appendChild(styleEl);
      }
    },
  });
  const mapRef = useRef<maplibregl.Map | null>(null);
  useEffect(() => {
    mapRef.current = mapInstance;
  }, [mapInstance]);

  // GSAP refs for entrance + crossfade
  const rootRef = useRef<HTMLDivElement | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);
  const mapWrapperRef = useRef<HTMLDivElement | null>(null);
  const previewBadgeRef = useRef<HTMLDivElement | null>(null);

  const [mode, setMode] = useState<Mode>("TVr");
  const [minTvr, setMinTvr] = useState(0);
  const [minTvrInput, setMinTvrInput] = useState(0);
  const [tvrStops, setTvrStops] = useState<Stop[]>(TVR_STOPS_DEFAULT);
  const [dplStops, setDplStops] = useState<Stop[]>(DPL_STOPS_DEFAULT);
  const [excludedFc, setExcludedFc] = useState<Set<number>>(new Set());
  const [showSegments, setShowSegments] = useState(true);
  const [showSensorsTv, setShowSensorsTv] = useState(true);
  const [showSensorsPl, setShowSensorsPl] = useState(true);
  const [searchValue, setSearchValue] = useState("");
  const [searchHint, setSearchHint] = useState<string | null>(null);

  // KPIs — incluent HPM (PM*) et HPS (PS*) en plus de TVr/DPL/capteurs.
  // Les champs PM/PS sont null tant que le GeoJSON segments ne les expose
  // pas (modeles HPM/HPS non charges dans la pipeline carte).
  const [kpis, setKpis] = useState<VisualisationKpis>(EMPTY_KPIS);

  // --- Sam welcome (only when truly empty) -------------------------------
  const samWelcomeShownRef = useRef(false);
  useEffect(() => {
    if (!active && !geoUploadResp && !samWelcomeShownRef.current) {
      samWelcomeShownRef.current = true;
      samNotify.welcome(
        "Voila a quoi ressemblera ta carte. Charge ton reseau GeoJSON + capteurs et clique sur Voir mes donnees.",
        { autoCloseMs: 9000 },
      );
    }
  }, [active, geoUploadResp]);

  // --- Mount entrance animations -----------------------------------------
  // Bandeau slide-in from left + map fade-in. useGSAP auto-cleanup on unmount.
  useGSAP(
    () => {
      if (!asideRef.current || !mapWrapperRef.current) return;
      const tl = gsap.timeline();
      tl.from(asideRef.current, {
        x: -24,
        autoAlpha: 0,
        duration: 0.45,
        ease: "power2.out",
      }).from(
        mapWrapperRef.current,
        {
          autoAlpha: 0,
          duration: 0.5,
          ease: "power2.out",
        },
        "<0.05",
      );
    },
    { scope: rootRef, dependencies: [] },
  );

  // --- Preview layer install (avant activation) --------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || active || previewLoadedRef.current) return;

    let cancelled = false;
    const ctrl = new AbortController();

    (async () => {
      try {
        const res = await fetch("/preview/visualisation-lyon.geojson", {
          signal: ctrl.signal,
        });
        if (!res.ok) throw new Error(`Preview: ${res.status}`);
        const data = (await res.json()) as GeoJSON.FeatureCollection;
        if (cancelled || !mapRef.current) return;

        if (!map.getSource("preview-segments")) {
          map.addSource("preview-segments", {
            type: "geojson",
            data: data as never,
          });
          // Preview = dataset reduit (~500 features) -> shine actif sans risque.
          addNeonLineLayers(map, {
            sourceId: "preview-segments",
            idPrefix: "preview-segments-tvr",
            field: "TVr",
            stops: TVR_STOPS_DEFAULT,
            enableShine: true,
          });
        }
        previewLoadedRef.current = true;
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        console.warn("Preview visualisation: dataset indisponible", err);
      }
    })();

    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [mapReady, active]);

  // --- Crossfade preview -> real data ------------------------------------
  // Quand on bascule en active=true et que les donnees reelles sont
  // installees, on fade-out les 3 couches preview (halo/core/shine) et on
  // remove la source.
  const removePreviewLayers = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const cleanup = () => {
      removeNeonLineLayers(map, "preview-segments-tvr", "preview-segments");
    };
    if (reduced || !map.getLayer("preview-segments-tvr-core")) {
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
          setNeonLineOpacity(map, "preview-segments-tvr", obj.o);
        } catch {
          /* layers gone */
        }
      },
      onComplete: cleanup,
    });
  }, []);

  // --- Uploads handlers ---------------------------------------------------

  const handleUploadGeo = useCallback(async (file: File) => {
    setGeoFile(file);
    setGeoUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      if (sensorUploadResp?.session_id) {
        form.append("session_id", sensorUploadResp.session_id);
      }
      const res = await apiClient.postForm<GeojsonUploadResponse>(
        "/api/visualisation/upload-geojson",
        form,
        { timeoutMs: 5 * 60_000 },
      );
      setGeoUploadResp(res);
      if (res.file_size_mb > 100) {
        toast.warning(
          `Fichier lourd (${res.file_size_mb.toFixed(0)} MB), le rendu peut prendre 10+ s`,
        );
      } else {
        toast.success(`GeoJSON charge : ${res.n_features} features`);
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      toast.error(`Upload GeoJSON echoue : ${msg}`);
      setUploadError(msg);
      setGeoFile(null);
    } finally {
      setGeoUploading(false);
    }
  }, [sensorUploadResp]);

  const handleUploadSensors = useCallback(async (file: File) => {
    setSensorFile(file);
    setSensorUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const sessionId = geoUploadResp?.session_id;
      if (!sessionId) {
        setSensorUploading(false);
        toast.message(
          "Fichier capteurs en attente : telechargez d'abord le GeoJSON.",
        );
        return;
      }
      form.append("session_id", sessionId);
      const res = await apiClient.postForm<SensorsUploadResponse>(
        "/api/visualisation/upload-sensors",
        form,
        { timeoutMs: 5 * 60_000 },
      );
      setSensorUploadResp(res);
      toast.success(
        `Capteurs charges : ${res.n_sensors} (${res.n_tv} TV, ${res.n_pl} PL)`,
      );
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      toast.error(`Upload capteurs echoue : ${msg}`);
      setUploadError(msg);
      setSensorFile(null);
    } finally {
      setSensorUploading(false);
    }
  }, [geoUploadResp]);

  // Auto-flush sensors si on les avait deposes avant le geojson
  useEffect(() => {
    if (
      sensorFile &&
      !sensorUploadResp &&
      !sensorUploading &&
      geoUploadResp?.session_id
    ) {
      handleUploadSensors(sensorFile);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geoUploadResp?.session_id]);

  const handleClearGeo = useCallback(() => {
    setGeoFile(null);
    setGeoUploadResp(null);
  }, []);

  const handleClearSensors = useCallback(() => {
    setSensorFile(null);
    setSensorUploadResp(null);
  }, []);

  // Bouton active quand le geojson est OK et aucun upload en vol.
  const canActivate = !!geoUploadResp && !geoUploading && !sensorUploading;

  const handleActivate = useCallback(() => {
    if (!canActivate) return;
    setActive(true);
  }, [canActivate]);

  // --- Streaming GETs (segments + sensors) -------------------------------

  useEffect(() => {
    if (!active || !geoUploadResp) return;
    let cancelled = false;
    const ctrl = new AbortController();

    async function loadBoth() {
      setLoading(true);
      try {
        const token = getToken();
        const headers: HeadersInit = token
          ? { Authorization: `Bearer ${token}` }
          : {};

        const segPromise = fetch(
          `${getApiBase()}/api/visualisation/geojson/${encodeURIComponent(geoUploadResp!.session_id)}`,
          { headers, credentials: "include", signal: ctrl.signal },
        );
        const senPromise = sensorUploadResp
          ? fetch(
              `${getApiBase()}/api/visualisation/sensors/${encodeURIComponent(sensorUploadResp.session_id)}`,
              { headers, credentials: "include", signal: ctrl.signal },
            )
          : Promise.resolve(null);

        const [segRes, senRes] = await Promise.all([segPromise, senPromise]);
        if (!segRes.ok) throw new Error(`Segments: ${segRes.status}`);
        if (senRes && !senRes.ok) throw new Error(`Capteurs: ${senRes.status}`);

        const segData = (await segRes.json()) as GeoJSON.FeatureCollection;
        const senData = senRes
          ? ((await senRes.json()) as GeoJSON.FeatureCollection)
          : null;
        if (cancelled) return;

        segData.features.forEach((f, i) => {
          if (f.id == null) {
            const aid = f.properties?.agregId;
            f.id = aid != null ? String(aid) : i;
          }
          // Retro-compat : alias bidirectionnel JOr <-> TVr (et min/max).
          // Le module accepte les anciens GeoJSON (TVr) et les nouveaux (JOr).
          const p = f.properties as Record<string, unknown> | undefined;
          if (p) {
            if (p.JOr == null && p.TVr != null) p.JOr = p.TVr;
            else if (p.TVr == null && p.JOr != null) p.TVr = p.JOr;
            if (p.JOrmin == null && p.TVrmin != null) p.JOrmin = p.TVrmin;
            else if (p.TVrmin == null && p.JOrmin != null) p.TVrmin = p.JOrmin;
            if (p.JOrmax == null && p.TVrmax != null) p.JOrmax = p.TVrmax;
            else if (p.TVrmax == null && p.JOrmax != null) p.TVrmax = p.JOrmax;
          }
        });

        segmentsDataRef.current = segData;
        sensorsDataRef.current = senData;

        setKpis(
          computeKpis(segData.features, senData ? senData.features.length : 0),
        );
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        const msg = err instanceof Error ? err.message : "Erreur inconnue";
        toast.error(`Chargement carte echoue : ${msg}`);
        setUploadError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadBoth();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [active, geoUploadResp, sensorUploadResp]);

  // --- Install real sources + layers + interactions ----------------------

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !active) return;
    if (!segmentsDataRef.current) return;

    const segmentsData = segmentsDataRef.current;
    const sensorsData = sensorsDataRef.current;

    if (map.getSource("segments")) {
      (map.getSource("segments") as maplibregl.GeoJSONSource).setData(
        segmentsData as never,
      );
    } else {
      map.addSource("segments", {
        type: "geojson",
        data: segmentsData as never,
        generateId: false,
      });

      // --- Neon 3-couches : TVr (mode chaud, defaut visible) + DPL (mode
      // froid, cache au demarrage). On desactive le shine au-dela d'un
      // certain volume de features pour preserver le FPS GPU sur 98k+
      // segments (cf. NEON_SHINE_MAX_FEATURES).
      const tooManyForShine = segmentsData.features.length > NEON_SHINE_MAX_FEATURES;

      // Opacite "core" : 1.0 en hover, 0.95 sinon (le halo reste constant a
      // ~0.55 pour le glow). On accepte un leger overdraw : c'est ce qui fait
      // l'effet neon.
      const coreHoverOpacity: unknown = [
        "case",
        ["boolean", ["feature-state", "hover"], false],
        1.0,
        0.95,
      ];

      addNeonLineLayers(map, {
        sourceId: "segments",
        idPrefix: "segments-tvr",
        field: "TVr",
        stops: tvrStops,
        visibility: "visible",
        enableShine: !tooManyForShine,
        coreOpacityExpr: coreHoverOpacity,
      });
      addNeonLineLayers(map, {
        sourceId: "segments",
        idPrefix: "segments-dpl",
        field: "DPL",
        stops: dplStops,
        visibility: "none",
        enableShine: !tooManyForShine,
        coreOpacityExpr: coreHoverOpacity,
      });

      // Couche "hit" : large, invisible, sert uniquement de cible pour les
      // events mousemove/click (evite d'avoir a viser pixel-perfect).
      // IMPORTANT : meme line-offset que les couches neon visibles, sinon le
      // hover designerait l'axe central (pas la ligne F/T effectivement
      // visible apres decalage lateral).
      map.addLayer({
        id: "segments-hit",
        type: "line",
        source: "segments",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#ffffff",
          "line-width": 14,
          "line-opacity": 0,
          "line-offset": bidirOffsetExpr() as never,
        },
      });

      map.on("mousemove", "segments-hit", (e) => {
        // Disambiguation F/T : MapLibre ignore line-offset au hit-test, on
        // doit choisir manuellement le feature dont la position VISUELLE
        // (apres offset) est la plus proche du curseur, sinon le hover
        // designe arbitrairement F ou T (cf. lib/map/ft-disambiguate.ts).
        const disambiguated = disambiguateFTClick(map, e);
        const f = disambiguated.features?.[0];
        if (!f) return;
        if (
          hoveredIdRef.current != null &&
          hoveredIdRef.current !== f.id
        ) {
          map.setFeatureState(
            { source: "segments", id: hoveredIdRef.current },
            { hover: false },
          );
        }
        hoveredIdRef.current = f.id ?? null;
        if (f.id != null) {
          map.setFeatureState(
            { source: "segments", id: f.id },
            { hover: true },
          );
        }
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "segments-hit", () => {
        if (hoveredIdRef.current != null) {
          map.setFeatureState(
            { source: "segments", id: hoveredIdRef.current },
            { hover: false },
          );
          hoveredIdRef.current = null;
        }
        map.getCanvas().style.cursor = "";
      });

      map.on("click", "segments-hit", (e) => {
        // Disambiguation F/T : sans ce filtre, MapLibre peut retourner
        // arbitrairement le feature -F ou -T sous le curseur (les deux
        // partagent la meme geometrie, line-offset ignore au hit-test).
        // Voir lib/map/ft-disambiguate.ts pour l'algo (projection visuelle).
        const disambiguated = disambiguateFTClick(map, e);
        const f = disambiguated.features?.[0];
        if (!f) return;
        const orig = segmentsDataRef.current?.features.find(
          (ff) => String(ff.id) === String(f.id),
        );
        let center: [number, number] | null = null;
        if (orig?.geometry) {
          const g = orig.geometry as GeoJSON.Geometry;
          if (g.type === "LineString") {
            center = midPoint(g.coordinates as number[][]);
          } else if (g.type === "MultiLineString") {
            const first = (g.coordinates as number[][][])[0];
            center = midPoint(first);
          }
        }
        if (popupRef.current) popupRef.current.remove();
        const html = segmentPopupHtml({
          props: (f.properties ?? {}) as Record<string, unknown>,
          center,
        });
        const lngLat = center
          ? new maplibregl.LngLat(center[0], center[1])
          : e.lngLat;
        const popup = new maplibregl.Popup({
          closeButton: true,
          maxWidth: "380px",
          offset: 8,
        })
          .setLngLat(lngLat)
          .setHTML(html)
          .addTo(map);
        popupRef.current = popup;

        setTimeout(() => {
          const el = popup
            .getElement()
            ?.querySelector<HTMLButtonElement>("[data-copy-id]");
          if (el) {
            el.addEventListener("click", () => {
              const id = el.getAttribute("data-copy-id") ?? "";
              if (id && navigator.clipboard) {
                navigator.clipboard.writeText(id).then(
                  () => toast.success(`ID copie : ${id}`),
                  () => toast.error("Copie impossible"),
                );
              }
            });
          }
        }, 0);
      });
    }

    if (sensorsData) {
      if (map.getSource("sensors")) {
        (map.getSource("sensors") as maplibregl.GeoJSONSource).setData(
          sensorsData as never,
        );
      } else {
        map.addSource("sensors", {
          type: "geojson",
          data: sensorsData as never,
          cluster: false,
        });

        // Sensors TV/PL : palette adaptee au fond satellite. Stroke blanc
        // epais (2px) + leger radius bonus pour pop contre la vegetation.
        installSensorLayers(map, { sourceId: "sensors" });

        const sensorClick = (
          e: maplibregl.MapMouseEvent & { features?: maplibregl.MapGeoJSONFeature[] },
        ) => {
          const f = e.features?.[0];
          if (!f) return;
          const g = f.geometry as GeoJSON.Geometry;
          let center: [number, number] | null = null;
          if (g.type === "Point") {
            const c = g.coordinates as number[];
            center = [Number(c[0]), Number(c[1])];
          }
          if (popupRef.current) popupRef.current.remove();
          const html = sensorPopupHtml({
            props: (f.properties ?? {}) as Record<string, unknown>,
            center,
          });
          const lngLat = center
            ? new maplibregl.LngLat(center[0], center[1])
            : e.lngLat;
          const popup = new maplibregl.Popup({
            closeButton: true,
            maxWidth: "340px",
            offset: 8,
          })
            .setLngLat(lngLat)
            .setHTML(html)
            .addTo(map);
          popupRef.current = popup;
        };

        map.on("click", "sensors-tv", sensorClick);
        map.on("click", "sensors-pl", sensorClick);
        map.on("mouseenter", "sensors-tv", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "sensors-tv", () => {
          map.getCanvas().style.cursor = "";
        });
        map.on("mouseenter", "sensors-pl", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "sensors-pl", () => {
          map.getCanvas().style.cursor = "";
        });
      }
    }

    realLayersInstalledRef.current = true;
    // Crossfade preview -> real
    removePreviewLayers();

    const bbox = geoUploadResp?.bbox ?? sensorUploadResp?.bbox ?? null;
    if (bbox && bbox.length === 4) {
      const reduced =
        typeof window !== "undefined" &&
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      map.fitBounds(
        [
          [bbox[0], bbox[1]],
          [bbox[2], bbox[3]],
        ],
        {
          padding: 60,
          maxZoom: 14,
          duration: reduced ? 0 : 800,
        },
      );
    }
  }, [mapReady, active, geoUploadResp, sensorUploadResp, kpis, removePreviewLayers, tvrStops, dplStops]);

  // --- Live update line-color quand l'user modifie les paliers -----------
  // Met a jour halo + core en une passe (shine reste blanc).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    updateNeonLineColor(map, "segments-tvr", tvrStops, "TVr");
    updateNeonLineColor(map, "segments-dpl", dplStops, "DPL");
  }, [tvrStops, dplStops, mapReady]);

  // --- Mode toggle (TVr vs DPL) -------------------------------------------
  // Bascule les 3 couches (halo/core/shine) du mode en cours.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !active) return;
    if (!map.getLayer("segments-tvr-core") || !map.getLayer("segments-dpl-core"))
      return;
    setNeonLineVisibility(map, "segments-tvr", mode === "TVr" && showSegments);
    setNeonLineVisibility(map, "segments-dpl", mode === "DPL" && showSegments);
  }, [mode, mapReady, showSegments, active]);

  // --- Filters : minTvr + excludedFc --------------------------------------
  useEffect(() => {
    const t = setTimeout(() => setMinTvr(minTvrInput), 100);
    return () => clearTimeout(t);
  }, [minTvrInput]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !active) return;
    if (!map.getLayer("segments-tvr-core")) return;

    const conditions: unknown[] = ["all"];
    if (minTvr > 0) {
      conditions.push([">=", ["to-number", ["get", "TVr"], 0], minTvr]);
    }
    if (excludedFc.size > 0) {
      for (const fc of excludedFc) {
        conditions.push(["!=", ["to-number", ["get", "FC"], 0], fc]);
      }
    }
    const expr = conditions.length === 1 ? null : conditions;
    // Applique le filtre aux 3 couches neon de chaque mode + a la couche hit.
    setNeonLineFilter(map, "segments-tvr", expr);
    setNeonLineFilter(map, "segments-dpl", expr);
    if (map.getLayer("segments-hit")) {
      map.setFilter("segments-hit", expr as never);
    }
  }, [minTvr, excludedFc, mapReady, active]);

  // --- Sensor layer visibility --------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !active) return;
    if (map.getLayer("sensors-tv")) {
      map.setLayoutProperty(
        "sensors-tv",
        "visibility",
        showSensorsTv ? "visible" : "none",
      );
    }
    if (map.getLayer("sensors-pl")) {
      map.setLayoutProperty(
        "sensors-pl",
        "visibility",
        showSensorsPl ? "visible" : "none",
      );
    }
  }, [showSensorsTv, showSensorsPl, mapReady, active]);

  // --- Search agregId -----------------------------------------------------
  const handleSearch = useCallback(() => {
    const map = mapRef.current;
    const data = segmentsDataRef.current;
    if (!map || !data || !searchValue.trim()) return;

    const needle = searchValue.trim();
    const match = data.features.find((f) => {
      const id = String(f.properties?.agregId ?? "");
      return id === needle || id.includes(needle);
    });
    if (!match) {
      setSearchHint(`Aucun segment avec agregId contenant "${needle}".`);
      return;
    }
    const g = match.geometry as GeoJSON.Geometry;
    let center: [number, number] | null = null;
    if (g.type === "LineString") {
      center = midPoint(g.coordinates as number[][]);
    } else if (g.type === "MultiLineString") {
      const first = (g.coordinates as number[][][])[0];
      center = midPoint(first);
    }
    if (!center) {
      setSearchHint("Segment trouve mais geometrie invalide.");
      return;
    }
    setSearchHint(`Segment ${match.properties?.agregId} centre.`);

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const flyDuration = reduced ? 0 : 1200;
    const popupDelay = reduced ? 0 : 1250;

    map.flyTo({
      center,
      zoom: 16,
      duration: flyDuration,
      essential: true,
    });

    setTimeout(() => {
      if (popupRef.current) popupRef.current.remove();
      const html = segmentPopupHtml({
        props: (match.properties ?? {}) as Record<string, unknown>,
        center,
      });
      const popup = new maplibregl.Popup({
        closeButton: true,
        maxWidth: "380px",
        offset: 8,
      })
        .setLngLat(center!)
        .setHTML(html)
        .addTo(map);
      popupRef.current = popup;
      setTimeout(() => {
        const el = popup
          .getElement()
          ?.querySelector<HTMLButtonElement>("[data-copy-id]");
        if (el) {
          el.addEventListener("click", () => {
            const id = el.getAttribute("data-copy-id") ?? "";
            if (id && navigator.clipboard) {
              navigator.clipboard.writeText(id).then(
                () => toast.success(`ID copie : ${id}`),
                () => toast.error("Copie impossible"),
              );
            }
          });
        }
      }, 0);
    }, popupDelay);
  }, [searchValue]);

  const handleResetFilters = useCallback(() => {
    setMinTvrInput(0);
    setExcludedFc(new Set());
    setShowSensorsTv(true);
    setShowSensorsPl(true);
    setShowSegments(true);
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

  const toggleFc = useCallback((fc: number) => {
    setExcludedFc((prev) => {
      const next = new Set(prev);
      if (next.has(fc)) next.delete(fc);
      else next.add(fc);
      return next;
    });
  }, []);

  // --- Resize map quand le bandeau change de contenu ----------------------
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
  }, [active]);

  // --- Render -------------------------------------------------------------

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
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-[#a0b0d8] hover:text-[#e6edf3] hover:bg-[rgba(255,255,255,.05)] transition-colors text-xs font-medium cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]"
            aria-label="Retour a l'accueil"
          >
            <ArrowLeft size={14} />
            <span>Retour</span>
          </button>
          <div className="hidden sm:block w-px h-5 bg-[#1f2740]" aria-hidden />
          <div className="flex items-center gap-2 min-w-0">
            <MapPinned size={16} className="text-[#FFB000] shrink-0" />
            {/* Titre en amber (#FFB000) : couleur accent du projet, lisible
                sur le header sombre comme sur les fonds clairs en overlay. */}
            <h1 className="text-sm font-semibold text-[#FFB000] truncate">
              Visualisation carte + compteurs
            </h1>
          </div>
          {active && geoUploadResp && (
            <div className="ml-auto flex items-center gap-2 text-[11px] text-[#a0b0d8] font-mono">
              <span className="hidden md:inline">
                session {geoUploadResp.session_id.slice(0, 8)}
              </span>
            </div>
          )}
        </div>
      </header>

      {/* KPIs (only when active) */}
      {active && (
        <section
          className="border-b border-[#1f2740] bg-[rgba(15,20,36,.4)]"
          aria-label="Indicateurs cle"
        >
          {/* Grid auto-adaptatif : 4 colonnes par defaut, 6 si HPM/HPS
              presents pour eviter le wrap visuel des cards supplementaires.
              UX5 : RevealOnScroll stagger des KPI cards quand on bascule
              en mode actif (premier rendu seulement). */}
          <RevealOnScroll
            variant="slide-up"
            stagger={0.05}
            distance={12}
            className={cn(
              "max-w-[1600px] mx-auto px-4 py-3 grid grid-cols-2 gap-3",
              kpis.pmMedian != null || kpis.psMedian != null
                ? "md:grid-cols-3 xl:grid-cols-6"
                : "md:grid-cols-4",
            )}
          >
            <KpiCard
              label="Segments charges"
              value={fmt(kpis.nSegments)}
              icon={<LayersIcon />}
            />
            <KpiCard
              label="JOr median"
              value={fmt(kpis.tvrMedian, "v/j")}
              icon={<Car />}
              hint={
                kpis.tvrMax != null ? `max ${fmt(kpis.tvrMax, "v/j")}` : undefined
              }
            />
            <KpiCard
              label="DPL median"
              value={fmt(kpis.dplMedian, "PL/j")}
              icon={<Truck />}
            />
            {/* HPM (PM) — visible uniquement si le modele HPM est charge
                cote pipeline carte (props.PM expose sur les segments). */}
            {kpis.pmMedian != null && (
              <KpiCard
                label="PM median"
                value={fmt(kpis.pmMedian, "v/h")}
                icon={<Sunrise />}
                hint={
                  kpis.pmMax != null
                    ? `max ${fmt(kpis.pmMax, "v/h")} · ${fmt(kpis.nSegmentsPmPos)} segs`
                    : undefined
                }
              />
            )}
            {/* HPS (PS) — idem HPM, conditionne au modele HPS. */}
            {kpis.psMedian != null && (
              <KpiCard
                label="PS median"
                value={fmt(kpis.psMedian, "v/h")}
                icon={<Sunset />}
                hint={
                  kpis.psMax != null
                    ? `max ${fmt(kpis.psMax, "v/h")} · ${fmt(kpis.nSegmentsPsPos)} segs`
                    : undefined
                }
              />
            )}
            {sensorUploadResp ? (
              <KpiCard
                label="Capteurs"
                value={fmt(kpis.nSensors)}
                icon={<Activity />}
                hint={`${sensorUploadResp.n_tv} TV / ${sensorUploadResp.n_pl} PL`}
              />
            ) : (
              <KpiCard
                label="Segments JOr > 0"
                value={fmt(kpis.nSegmentsTvrPos)}
                icon={<Activity />}
                hint="aucun capteur charge"
              />
            )}
          </RevealOnScroll>
        </section>
      )}

      {/* Bandeau + Map unifie */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0">
        <aside
          ref={asideRef}
          // NIT 2 : sticky sur grand ecran. top-12 ~= hauteur du header (48px).
          // L'overflow-y-auto reste actif et permet de scroller dans l'aside
          // independamment du flux principal (cf. mode actif avec filtres).
          className="w-full lg:w-[380px] lg:shrink-0 lg:sticky lg:top-12 lg:self-start border-r border-[#1f2740] bg-[rgba(15,20,36,.94)] px-4 py-4 space-y-4 overflow-y-auto"
          aria-label={active ? "Filtres et legende" : "Chargement des donnees"}
          style={{ maxHeight: active ? "calc(100vh - 9rem)" : undefined }}
        >
          {!active ? (
            <UploadBandeau
              geoFile={geoFile}
              sensorFile={sensorFile}
              geoUploading={geoUploading}
              sensorUploading={sensorUploading}
              geoUploadResp={geoUploadResp}
              sensorUploadResp={sensorUploadResp}
              uploadError={uploadError}
              canActivate={canActivate}
              onUploadGeo={handleUploadGeo}
              onUploadSensors={handleUploadSensors}
              onClearGeo={handleClearGeo}
              onClearSensors={handleClearSensors}
              onActivate={handleActivate}
            />
          ) : (
            <ActiveSidebar
              mode={mode}
              onMode={setMode}
              minTvrInput={minTvrInput}
              onMinTvrInput={setMinTvrInput}
              excludedFc={excludedFc}
              onToggleFc={toggleFc}
              showSegments={showSegments}
              onShowSegments={() => setShowSegments((v) => !v)}
              showSensorsTv={showSensorsTv}
              onShowSensorsTv={() => setShowSensorsTv((v) => !v)}
              showSensorsPl={showSensorsPl}
              onShowSensorsPl={() => setShowSensorsPl((v) => !v)}
              hasSensors={!!sensorUploadResp}
              searchValue={searchValue}
              onSearchValue={(v) => {
                setSearchValue(v);
                setSearchHint(null);
              }}
              onSearch={handleSearch}
              searchHint={searchHint}
              tvrStops={tvrStops}
              setTvrStops={setTvrStops}
              dplStops={dplStops}
              setDplStops={setDplStops}
              onResetFilters={handleResetFilters}
            />
          )}
        </aside>

        {/* Map (single instance) — NIT 1 : <section> au lieu de <main> pour
            eviter le double <main> avec le root layout. */}
        <section
          ref={mapWrapperRef}
          role="region"
          className="flex-1 relative min-h-[480px] lg:min-h-0"
          aria-label="Carte interactive"
          style={{ background: "#0d1117" }}
        >
          {/* Badge "Mode apercu" (visible uniquement avant activation).
              Avec un fond de carte clair par defaut (Voyager), on utilise une
              variante "solide ambree" qui reste lisible sur clair ET sur sombre. */}
          {!active && (
            <div
              ref={previewBadgeRef}
              className="absolute top-3 left-1/2 -translate-x-1/2 z-10 pointer-events-none"
              role="status"
              aria-live="polite"
            >
              {/* UX5 : badge "Apercu Lyon" ShimmerText gold + NeonBorder
                  amber subtil. Conserve la lisibilite sur fond clair (Voyager)
                  comme sur fond sombre. */}
              <NeonBorder tone="amber" speed={3.4} rotate={false} className="rounded-full">
                <div className="px-3 py-1.5 rounded-full flex items-center gap-2">
                  <Eye size={12} aria-hidden className="text-[#FFB000]" />
                  <ShimmerText variant="gold" className="text-xs">
                    Apercu Lyon — depose tes donnees pour passer en mode reel
                  </ShimmerText>
                </div>
              </NeonBorder>
            </div>
          )}

          {loading && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-[rgba(13,17,23,.7)] backdrop-blur-sm">
              <Loader2 className="animate-spin text-[#22d3ee]" size={28} />
              <p className="mt-3 text-xs text-[#a0b0d8]">
                Chargement des donnees...
              </p>
            </div>
          )}
          {!loading && active && uploadError && (
            <div className="absolute inset-0 z-20 flex items-center justify-center p-4">
              <div className="rounded-xl border border-amber-500/30 bg-[rgba(15,20,36,.95)] p-5 max-w-sm space-y-3">
                <div className="flex items-center gap-2 text-amber-300">
                  <AlertTriangle size={18} />
                  <p className="text-sm font-semibold">Carte indisponible</p>
                </div>
                <p className="text-xs text-[#a0b0d8]">{uploadError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setActive(false);
                    setUploadError(null);
                  }}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#22d3ee] text-[#0d1117] text-xs font-semibold hover:bg-[#67e8f9] cursor-pointer"
                >
                  <X size={12} />
                  Reprendre les uploads
                </button>
              </div>
            </div>
          )}
          <div
            ref={mapContainerRef}
            className="absolute inset-0"
            style={{ position: "absolute", inset: 0 }}
          />
          {/* Switcher de fond de carte (top-right, sous les controles MapLibre).
              Le composant gere sa propre persistance localStorage + animations. */}
          <BasemapSwitcher mapRef={mapRef} />
        </section>
      </div>
    </div>
  );
}

// ===========================================================================
// UploadBandeau — reste inline (specifique a cette page, pas reutilise).
// ===========================================================================

function UploadBandeau({
  geoFile,
  sensorFile,
  geoUploading,
  sensorUploading,
  geoUploadResp,
  sensorUploadResp,
  uploadError,
  canActivate,
  onUploadGeo,
  onUploadSensors,
  onClearGeo,
  onClearSensors,
  onActivate,
}: {
  geoFile: File | null;
  sensorFile: File | null;
  geoUploading: boolean;
  sensorUploading: boolean;
  geoUploadResp: GeojsonUploadResponse | null;
  sensorUploadResp: SensorsUploadResponse | null;
  uploadError: string | null;
  canActivate: boolean;
  onUploadGeo: (f: File) => void;
  onUploadSensors: (f: File) => void;
  onClearGeo: () => void;
  onClearSensors: () => void;
  onActivate: () => void;
}) {
  const successRef = useRef<HTMLDivElement | null>(null);

  // Micro-interaction sur succes d'upload (geo confirme)
  useGSAP(() => {
    if (!successRef.current) return;
    gsap.fromTo(
      successRef.current,
      { scale: 0.92, autoAlpha: 0 },
      {
        scale: 1,
        autoAlpha: 1,
        duration: 0.4,
        ease: "back.out(1.6)",
      },
    );
  }, { dependencies: [!!geoUploadResp] });

  return (
    <div className="space-y-4">
      {/* Sam intro */}
      <div className="rounded-xl border border-[#22d3ee]/20 bg-gradient-to-br from-[rgba(34,211,238,.06)] to-transparent p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-[#22d3ee] shrink-0" />
          <h2 className="text-sm font-semibold text-[#e6edf3]">
            Charge tes donnees
          </h2>
        </div>
        <p className="text-[12px] text-[#a0b0d8] leading-relaxed">
          Importe un GeoJSON de segments (obligatoire) et un fichier de
          comptage capteurs (optionnel). La carte a droite est en{" "}
          <span className="text-amber-200">mode apercu</span> tant que tu
          n&apos;as pas active tes donnees.
        </p>
      </div>

      {uploadError && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-2 text-[11.5px] text-amber-200">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span>{uploadError}</span>
        </div>
      )}

      {/* Zone 1 : GeoJSON segments */}
      <div className="rounded-xl border border-[#1f2740] bg-[rgba(13,17,23,.5)] p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-[rgba(34,211,238,.1)] flex items-center justify-center text-[#22d3ee]">
            <LayersIcon size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[13px] font-semibold text-[#e6edf3] leading-tight">
              GeoJSON segments
            </h3>
            <p className="text-[10.5px] text-[#a0b0d8] leading-tight mt-0.5">
              .geojson, .json ou .parquet
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
          label="Depose le GeoJSON"
          description=".geojson, .json ou .parquet"
        />
        {geoUploading && (
          <div className="flex items-center gap-2 text-[11px] text-[#a0b0d8]">
            <Loader2 size={12} className="animate-spin text-[#22d3ee]" />
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
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">Colonnes</span>
              <span className="font-mono tabular-nums">
                {geoUploadResp.columns.length}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Zone 2 : Capteurs */}
      <div className="rounded-xl border border-[#1f2740] bg-[rgba(13,17,23,.5)] p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-[rgba(229,57,53,.12)] flex items-center justify-center text-[#e53935]">
            <Activity size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <h3 className="text-[13px] font-semibold text-[#e6edf3] leading-tight">
                Capteurs
              </h3>
              <span
                className="inline-flex items-center px-1.5 py-[1px] rounded text-[9px] font-semibold uppercase tracking-wide bg-[rgba(255,255,255,.06)] text-[#a0b0d8] border border-[#1f2740]"
                aria-label="Champ optionnel"
              >
                Optionnel
              </span>
            </div>
            <p className="text-[10.5px] text-[#a0b0d8] leading-tight mt-0.5">
              csv, xlsx, geojson, parquet
            </p>
          </div>
          {sensorUploadResp && (
            <CheckCircle2
              size={16}
              className="text-emerald-400 shrink-0"
              aria-label="Upload reussi"
            />
          )}
        </div>
        <DropZone
          file={sensorFile}
          onFile={onUploadSensors}
          onClear={onClearSensors}
          accept={{
            "text/csv": [".csv"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
              [".xlsx"],
            "application/vnd.ms-excel": [".xls"],
            "application/geo+json": [".geojson"],
            "application/json": [".json"],
            "application/octet-stream": [".parquet"],
          }}
          label="Depose le fichier capteurs"
          description="csv, xlsx, geojson, parquet"
        />
        {sensorUploading && (
          <div className="flex items-center gap-2 text-[11px] text-[#a0b0d8]">
            <Loader2 size={12} className="animate-spin text-[#22d3ee]" />
            <span>Upload en cours...</span>
          </div>
        )}
        {sensorFile && !sensorUploadResp && !sensorUploading && !geoUploadResp && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-[10.5px] text-amber-200 leading-snug">
            En attente : telecharge d&apos;abord le GeoJSON pour creer la
            session.
          </div>
        )}
        {sensorUploadResp && (
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 space-y-1 text-[11px] text-emerald-200">
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">Capteurs</span>
              <span className="font-mono tabular-nums">
                {NF_FR.format(sensorUploadResp.n_sensors)}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">TMJA TV &gt; 0</span>
              <span className="font-mono tabular-nums">
                {NF_FR.format(sensorUploadResp.n_tv)}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-[#a0b0d8]">TMJA PL &gt; 0</span>
              <span className="font-mono tabular-nums">
                {NF_FR.format(sensorUploadResp.n_pl)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Action button (sticky bottom) — UX5 : MagneticButton primary
          quand canActivate, fallback bouton disabled stylise sinon. Le NeonBorder
          cyan pulse autour du wrap pour signaler la pret-a-activer (idiome
          "ready to fire"). */}
      <div className="sticky bottom-0 -mx-4 px-4 pb-3 pt-3 bg-gradient-to-t from-[rgba(15,20,36,.98)] via-[rgba(15,20,36,.92)] to-transparent">
        {canActivate ? (
          <NeonBorder tone="cyan" speed={2.6} className="rounded-md">
            <MagneticButton
              variant="primary"
              size="md"
              onClick={onActivate}
              className="w-full bg-[#22d3ee] !text-[#0d1117] hover:bg-[#67e8f9] border-[#22d3ee]"
            >
              <Eye size={16} />
              Voir mes donnees
            </MagneticButton>
          </NeonBorder>
        ) : (
          <button
            type="button"
            disabled
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-[rgba(255,255,255,.05)] text-[#7d8aa8] cursor-not-allowed"
          >
            <Eye size={16} />
            Voir mes donnees
          </button>
        )}
        <p className="text-[10px] text-[#7d8aa8] mt-1.5 text-center">
          Astuce : un GeoJSON &gt; 100 MB peut prendre 10+ s a afficher.
        </p>
      </div>
    </div>
  );
}
