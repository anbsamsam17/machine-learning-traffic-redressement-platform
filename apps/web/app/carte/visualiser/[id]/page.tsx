"use client";

/**
 * Carte interactive — visualiseur de la carte des debits.
 *
 * Layout : Dashboard data-dense (override de la reco "marketplace") avec
 *  - Header sticky : retour + titre + export geojson
 *  - Sidebar 320px : KPI overview + filtres + recherche agregId + legende
 *  - Map MapLibre GL JS plein cadre, centree sur Grand Lyon (45.75, 4.85)
 *
 * Source des donnees :
 *  - `id = "dev-light"`  -> /api/carte/result-dev/light (echantillon 2025_light)
 *  - `id = <session_id>` -> /api/carte/result/{session_id}
 *
 * Le composant MapView (components/map/MapView.tsx) gere le rendu MapLibre,
 * les filtres setFilter, les popups hover/click, le bbox-fit et le respect
 * de prefers-reduced-motion.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Download,
  Search,
  Loader2,
  AlertTriangle,
  Layers,
  Car,
  Truck,
  Activity,
  Filter as FilterIcon,
  Crosshair,
} from "lucide-react";
import { toast } from "sonner";
import type { FeatureCollection, LineString, GeoJsonProperties, Feature } from "geojson";
import maplibregl from "maplibre-gl";

import { MapView, type MapViewFilters } from "@/components/map/MapView";
import { ControlPanel, type MapControlsState } from "@/components/map/ControlPanel";
import { TVR_STOPS } from "@/lib/map-palette";
import { apiClient } from "@/lib/api";
import { getApiBase } from "@/lib/api-url";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SegmentFeature = Feature<LineString, GeoJsonProperties>;
type SegmentCollection = FeatureCollection<LineString, GeoJsonProperties>;

interface KpiSnapshot {
  total: number;
  filtered: number;
  tvrMedian: number | null;
  tvrMax: number | null;
  dplMedian: number | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const NF_FR = new Intl.NumberFormat("fr-FR");

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

function fmt(v: number | null | undefined, unit?: string): string {
  if (v == null || !isFinite(v)) return "—";
  const out = NF_FR.format(Math.round(v as number));
  return unit ? `${out} ${unit}` : out;
}

/**
 * Compute KPIs over an arbitrary subset of features.
 * O(n) with two passes (extract + sort/median) — acceptable up to ~250k.
 */
function computeKpis(
  features: SegmentFeature[],
  filters: MapViewFilters,
): KpiSnapshot {
  let total = features.length;
  const tvr: number[] = [];
  const dpl: number[] = [];
  let tvrMax = 0;
  let filtered = 0;

  for (const f of features) {
    const props = f.properties || {};
    // Rename TVr -> JOr (cf carte.py changement 4) : on lit JOr en premier
    // puis fallback sur TVr pour les GeoJSON historiques.
    const tvrVal = Number(props.JOr ?? props.TVr ?? 0);
    const dplVal = Number(props.DPL ?? 0);
    const fcVal = Number(props.FC ?? 0);

    if (filters.minTvr != null && tvrVal < filters.minTvr) continue;
    if (filters.excludeFc1 && fcVal === 1) continue;

    filtered += 1;
    if (isFinite(tvrVal)) {
      tvr.push(tvrVal);
      if (tvrVal > tvrMax) tvrMax = tvrVal;
    }
    if (isFinite(dplVal)) dpl.push(dplVal);
  }

  return {
    total,
    filtered,
    tvrMedian: median(tvr),
    tvrMax: tvrMax > 0 ? tvrMax : null,
    dplMedian: median(dpl),
  };
}

/** Bbox of a single feature (used for flyTo target). */
function featureCentroid(f: SegmentFeature): [number, number] | null {
  const coords = f.geometry?.coordinates;
  if (!coords || coords.length === 0) return null;
  // Use the geometric midpoint of the LineString rather than the start
  // so the popup anchors visually on the segment, not at one of its tips.
  const mid = coords[Math.floor(coords.length / 2)];
  if (!mid || mid.length < 2) return null;
  return [mid[0], mid[1]];
}

// ---------------------------------------------------------------------------
// KPI card (sober, surface-elevated)
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
// Sidebar legend (mirrors MapView's overlay but lives in the side rail too,
// to satisfy the spec layout — the overlay version stays for users who
// hide the sidebar on narrow screens).
// ---------------------------------------------------------------------------

function SidebarLegend() {
  return (
    <div className="surface-elevated p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Layers size={12} className="text-accent" />
        <h4 className="text-[11px] font-semibold text-text uppercase tracking-wide">
          Legende JOr (veh/j)
        </h4>
      </div>
      <ul className="space-y-1.5" role="list">
        {TVR_STOPS.slice().reverse().map((stop) => (
          <li
            key={stop.min}
            className="flex items-center gap-2 text-[11px] text-text-muted"
          >
            <span
              aria-hidden
              className="inline-block h-2.5 w-6 rounded-sm shrink-0"
              style={{ background: stop.color }}
            />
            <span className="font-mono tabular-nums">{stop.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CarteVisualiserPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const sessionId = params?.id ?? "";

  // Geojson + loading state
  const [geojson, setGeojson] = useState<SegmentCollection | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadProgress, setLoadProgress] = useState(0); // 0..100 (when known)

  // Filter state (drives MapView setFilter)
  const [filters, setFilters] = useState<MapViewFilters>({
    minTvr: 0,
    excludeFc1: false,
  });

  // Search
  const [searchValue, setSearchValue] = useState("");
  const [searchHint, setSearchHint] = useState<string | null>(null);

  // Map handle exposed by MapView for flyTo + popup spawn
  const mapRef = useRef<maplibregl.Map | null>(null);

  // -------------------------------------------------------------------------
  // Resolve endpoint + fetch the geojson with streaming progress where
  // possible (Content-Length is set by FastAPI for FileResponse).
  // -------------------------------------------------------------------------

  const endpointPath = useMemo(() => {
    if (!sessionId) return null;
    return sessionId === "dev-light"
      ? "/api/carte/result-dev/light"
      : `/api/carte/result/${encodeURIComponent(sessionId)}`;
  }, [sessionId]);

  useEffect(() => {
    if (!endpointPath) return;

    let cancelled = false;
    const ctrl = new AbortController();

    async function load() {
      setLoading(true);
      setLoadError(null);
      setLoadProgress(0);

      try {
        const token = getToken();
        const url = endpointPath!.startsWith("http")
          ? endpointPath!
          : `${getApiBase()}${endpointPath}`;
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
            // ignore — keep default detail
          }
          throw new Error(detail);
        }

        // Stream the body so we can update a progress bar (Content-Length is
        // set by FastAPI for the FileResponse dev endpoint; absent for the
        // live JSONResponse path — fall back to indeterminate then).
        const total = Number(res.headers.get("Content-Length") || 0);
        const reader = res.body?.getReader();
        if (reader && total > 0) {
          const chunks: Uint8Array[] = [];
          let received = 0;
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            if (value) {
              chunks.push(value);
              received += value.length;
              setLoadProgress(Math.min(99, Math.round((received / total) * 100)));
            }
          }
          if (cancelled) return;
          const blob = new Blob(chunks, { type: "application/json" });
          const text = await blob.text();
          const data = JSON.parse(text) as SegmentCollection;
          setGeojson(data);
          setLoadProgress(100);
        } else {
          // No Content-Length — load synchronously.
          const data = (await res.json()) as SegmentCollection;
          if (cancelled) return;
          setGeojson(data);
          setLoadProgress(100);
        }
      } catch (err: unknown) {
        if ((err as Error).name === "AbortError") return;
        const message = err instanceof Error ? err.message : "Erreur inconnue";
        setLoadError(message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();

    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [endpointPath]);

  // -------------------------------------------------------------------------
  // KPIs — recomputed on data or filter change.
  // -------------------------------------------------------------------------

  const kpis = useMemo<KpiSnapshot>(() => {
    if (!geojson) {
      return { total: 0, filtered: 0, tvrMedian: null, tvrMax: null, dplMedian: null };
    }
    return computeKpis(geojson.features, filters);
  }, [geojson, filters]);

  // -------------------------------------------------------------------------
  // ControlPanel bridge — translate its state shape into MapViewFilters
  // -------------------------------------------------------------------------

  const controlsState: MapControlsState = useMemo(
    () => ({
      minTvrFilter: filters.minTvr ?? 0,
      excludeFc1: filters.excludeFc1 ?? false,
    }),
    [filters.minTvr, filters.excludeFc1],
  );

  const onControlsChange = useCallback((next: MapControlsState) => {
    setFilters({
      minTvr: next.minTvrFilter,
      excludeFc1: next.excludeFc1,
    });
  }, []);

  // -------------------------------------------------------------------------
  // Search by agregId — flyTo + popup
  // -------------------------------------------------------------------------

  const handleSearch = useCallback(() => {
    if (!geojson || !searchValue.trim()) return;
    const needle = searchValue.trim();
    const match = geojson.features.find((f) => {
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

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    // When prefers-reduced-motion is set, MapLibre runs flyTo synchronously
    // (duration 0). Aligning the popup-spawn timeout means the popup appears
    // immediately instead of after a phantom 1250ms wait.
    const flyDuration = reduced ? 0 : 1200;
    const popupDelay = reduced ? 0 : 1250;

    map.flyTo({
      center: center as [number, number],
      zoom: 16,
      duration: flyDuration,
      essential: true,
    });

    // Open a popup once the flyTo lands. We reuse maplibre's popup; the popup
    // HTML mirrors what MapView's click handler builds (renderPopupHTML).
    setTimeout(
      () => {
        const props = (match.properties ?? {}) as Record<string, unknown>;
        const html = renderQuickPopup(props);
        new maplibregl.Popup({ closeButton: true, maxWidth: "280px", offset: 8 })
          .setLngLat(center as [number, number])
          .setHTML(html)
          .addTo(map);
      },
      popupDelay,
    );
  }, [geojson, searchValue]);

  // -------------------------------------------------------------------------
  // Download — same data we already have client-side, but go through apiClient
  // so we keep the Bearer auth + same filename convention as /carte page.
  // -------------------------------------------------------------------------

  const handleDownload = useCallback(() => {
    if (sessionId === "dev-light") {
      // Dev endpoint — trigger native download via apiClient
      apiClient
        .download("/api/carte/result-dev/light", "2025_light.geojson")
        .catch((err: Error) =>
          toast.error(`Telechargement echoue : ${err.message}`),
        );
      return;
    }
    if (!sessionId) return;
    apiClient
      .download(
        `/api/carte/download/${sessionId}`,
        `carte_debits_${sessionId.slice(0, 8)}.geojson`,
      )
      .catch((err: Error) =>
        toast.error(`Telechargement echoue : ${err.message}`),
      );
  }, [sessionId]);

  // -------------------------------------------------------------------------
  // Capture MapView's underlying map instance via a ref-forwarding trick :
  // we listen on the global window for the `__carteMap` handle that MapView
  // exposes (see patch in MapView.tsx). Falls back gracefully if absent.
  // -------------------------------------------------------------------------

  useEffect(() => {
    function onReady(evt: Event) {
      const detail = (evt as CustomEvent<{ map: maplibregl.Map }>).detail;
      if (detail?.map) mapRef.current = detail.map;
    }
    window.addEventListener("carte-map-ready", onReady as EventListener);
    return () => window.removeEventListener("carte-map-ready", onReady as EventListener);
  }, []);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="flex flex-col min-h-[calc(100vh-3rem)]">
      {/* Header */}
      <header
        className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80"
        role="banner"
      >
        <div className="max-w-[1600px] mx-auto px-4 py-3 flex items-center gap-4">
          <button
            type="button"
            onClick={() => router.push("/carte")}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-text-muted hover:text-text hover:bg-bg-elevated transition-colors text-xs font-medium cursor-pointer"
            aria-label="Retour a la page Carte"
          >
            <ArrowLeft size={14} />
            <span>Retour</span>
          </button>

          <div className="hidden sm:block w-px h-5 bg-border" aria-hidden />

          <div className="flex items-baseline gap-2 min-w-0">
            <h1 className="text-sm font-semibold text-text truncate">
              Carte interactive — Grand Lyon
            </h1>
            <span className="text-[11px] text-text-muted font-mono truncate hidden md:inline">
              {sessionId === "dev-light"
                ? "echantillon 2025_light"
                : `session ${sessionId.slice(0, 8)}`}
            </span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={handleDownload}
              disabled={!geojson || loading}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium cursor-pointer transition-colors",
                "bg-success text-white hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed",
              )}
              title="Telecharger le geojson"
            >
              <Download size={14} />
              <span className="hidden sm:inline">Telecharger geojson</span>
            </button>
          </div>
        </div>
      </header>

      {/* KPI row */}
      <section
        className="border-b border-border bg-bg-elevated/30"
        aria-label="Indicateurs cle"
      >
        <div className="max-w-[1600px] mx-auto px-4 py-3 grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard
            label="Troncons charges"
            value={fmt(kpis.total)}
            icon={<Layers />}
            hint={
              kpis.filtered !== kpis.total
                ? `${fmt(kpis.filtered)} affiches`
                : undefined
            }
          />
          <KpiCard
            label="JOr median"
            value={fmt(kpis.tvrMedian, "veh/j")}
            icon={<Car />}
          />
          <KpiCard
            label="JOr maximum"
            value={fmt(kpis.tvrMax, "veh/j")}
            icon={<Activity />}
          />
          <KpiCard
            label="DPL median"
            value={fmt(kpis.dplMedian, "PL/j")}
            icon={<Truck />}
          />
        </div>
      </section>

      {/* Main split : sidebar + map */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0">
        {/* Sidebar */}
        <aside
          className="w-full lg:w-[320px] lg:shrink-0 border-r border-border bg-bg-elevated/40 px-4 py-4 space-y-4 overflow-y-auto"
          aria-label="Filtres et legende"
        >
          {/* Filters (ControlPanel) */}
          <div className="surface-elevated p-3">
            <ControlPanel
              state={controlsState}
              onChange={onControlsChange}
              hasData={!!geojson}
              featureCount={kpis.filtered}
              meanTvr={kpis.tvrMedian}
              meanDpl={kpis.dplMedian}
            />
          </div>

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
                onChange={(e) => {
                  setSearchValue(e.target.value);
                  setSearchHint(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSearch();
                }}
                placeholder="Identifiant complet ou partiel"
                disabled={!geojson}
                className="flex-1 h-8 rounded border border-border bg-bg-elevated px-2 text-xs text-text outline-none focus:border-accent disabled:opacity-50"
                aria-label="Identifiant agregId"
              />
              <button
                type="button"
                onClick={handleSearch}
                disabled={!geojson || !searchValue.trim()}
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

          {/* Legend (inline copy, mirrors the map overlay so it stays
              visible even if the operator hides the overlay) */}
          <SidebarLegend />

          {/* Tip / source */}
          <div className="rounded border border-border bg-bg-elevated/50 px-3 py-2.5 text-[10px] text-text-muted leading-relaxed">
            <p>
              <FilterIcon size={10} className="inline -mt-0.5 mr-1" />
              Les filtres modifient l&apos;affichage sans recharger la carte.
              Cliquez sur un troncon pour voir le detail.
            </p>
          </div>
        </aside>

        {/* Map */}
        <main
          className="flex-1 min-h-[480px] lg:min-h-0 relative bg-bg-elevated"
          aria-label="Carte interactive des debits"
        >
          {/* Loading overlay */}
          {loading && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-bg/70 backdrop-blur-sm">
              <Loader2 className="animate-spin text-accent" size={28} />
              <p className="mt-3 text-xs text-text-muted">
                Chargement de la carte...
              </p>
              {loadProgress > 0 && (
                <div className="mt-3 w-56 h-1.5 rounded-full bg-bg-subtle overflow-hidden">
                  <div
                    className="h-full bg-accent transition-[width] duration-200"
                    style={{ width: `${loadProgress}%` }}
                  />
                </div>
              )}
              {loadProgress > 0 && (
                <p className="mt-1.5 text-[10px] text-text-subtle tabular-nums">
                  {loadProgress}%
                </p>
              )}
            </div>
          )}

          {/* Error overlay */}
          {!loading && loadError && (
            <div className="absolute inset-0 z-20 flex items-center justify-center p-4">
              <div className="surface-elevated p-5 max-w-sm space-y-3 border-danger/40">
                <div className="flex items-center gap-2 text-danger">
                  <AlertTriangle size={18} />
                  <p className="text-sm font-semibold">Carte indisponible</p>
                </div>
                <p className="text-xs text-text-muted">{loadError}</p>
                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => router.push("/carte")}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-accent text-accent-fg text-xs font-medium hover:bg-indigo-600 cursor-pointer"
                  >
                    Retour generation
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Map (MapView mounts the basemap, the geojson source/layer, and
              registers hover + click handlers) */}
          <MapView
            geojson={geojson}
            filters={filters}
            theme="dark"
            className="h-full"
          />
        </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quick popup HTML — kept local so the search-result popup matches the click
// popup. Mirrors the structure of components/map/MapPopup.tsx without the
// shared import (avoids coupling the page to the popup module's private API).
// ---------------------------------------------------------------------------

function renderQuickPopup(p: Record<string, unknown>): string {
  const mono = "ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace";
  const cell = (label: string, value: string) =>
    `<div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span style="color:#94a3b8;font-size:11px">${label}</span><span style="color:#f8fafc;font-size:12px;font-family:${mono};font-variant-numeric:tabular-nums">${value}</span></div>`;
  const num = (v: unknown, unit?: string): string => {
    const n = Number(v);
    if (!isFinite(n)) return "—";
    return unit ? `${NF_FR.format(Math.round(n))} ${unit}` : NF_FR.format(Math.round(n));
  };
  const range = (lo: unknown, hi: unknown): string => {
    const a = Number(lo);
    const b = Number(hi);
    if (!isFinite(a) && !isFinite(b)) return "—";
    if (!isFinite(a)) return `≤ ${NF_FR.format(Math.round(b))}`;
    if (!isFinite(b)) return `≥ ${NF_FR.format(Math.round(a))}`;
    return `${NF_FR.format(Math.round(a))} – ${NF_FR.format(Math.round(b))}`;
  };
  return `
    <div style="font-family:Inter,system-ui,sans-serif;color:#f8fafc;min-width:220px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,.1)">
        <span style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em">Troncon</span>
        <span style="font-size:11px;font-family:${mono};color:#a5b4fc">#${p.agregId ?? "—"}</span>
      </div>
      ${cell("JOr", num(p.JOr ?? p.TVr, "veh/j"))}
      ${cell("DPL", num(p.DPL, "PL/j"))}
      ${p.VLred != null ? cell("VLred", num(p.VLred, "veh/j")) : ""}
      ${p.PLred != null ? cell("PLred", num(p.PLred, "PL/j")) : ""}
      ${cell("IC JOr", range(p.JOrmin ?? p.TVrmin, p.JOrmax ?? p.TVrmax))}
      ${cell("IC DPL", range(p.DPLmin, p.DPLmax))}
      ${p.FC != null ? cell("FC", String(p.FC)) : ""}
    </div>
  `;
}
