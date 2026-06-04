"use client";

/**
 * Visualiseur de la carte d'evolution des debits.
 *
 * Reutilise le composant MapView (components/map/MapView.tsx) mais :
 *   - charge /api/evolution/result/{id} (FeatureCollection LineString),
 *   - colore par JOr (%) avec une palette DIVERGENTE rouge<->vert centree
 *     sur 0, clampee a +/-100% (cf lib/evolution-palette),
 *   - attenue les troncons sig=0 (opacite reduite),
 *   - popup : T1, T2, JOr (%), dJOr, categorie, match_level, sig.
 *
 * MapView est parametre via des props OPTIONNELLES (paintOverrides,
 * renderPopup, hideDefaultLegend) ajoutees sans casser l'usage carte.
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
  TrendingUp,
  TrendingDown,
  Crosshair,
  Filter as FilterIcon,
} from "lucide-react";
import { toast } from "sonner";
import type {
  FeatureCollection,
  LineString,
  GeoJsonProperties,
  Feature,
} from "geojson";
import maplibregl from "maplibre-gl";

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
import { apiClient } from "@/lib/api";
import { getApiBase } from "@/lib/api-url";
import { getToken } from "@/lib/auth";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SegmentFeature = Feature<LineString, GeoJsonProperties>;
type SegmentCollection = FeatureCollection<LineString, GeoJsonProperties>;

interface EvolutionKpis {
  total: number;
  hausses: number; // JOr > 0
  baisses: number; // JOr < 0
  significatifs: number; // sig === 1
  medianJor: number | null; // mediane des JOr non null (%)
}

const NF_FR = new Intl.NumberFormat("fr-FR");

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

// ---------------------------------------------------------------------------
// Popup HTML — dJOr (veh/j, primaire) / JOr% (secondaire) / T1 / T2 /
// match_level / sig
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
// Page
// ---------------------------------------------------------------------------

export default function EvolutionVisualiserPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const sessionId = params?.id ?? "";

  const [geojson, setGeojson] = useState<SegmentCollection | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadProgress, setLoadProgress] = useState(0);

  const [searchValue, setSearchValue] = useState("");
  const [searchHint, setSearchHint] = useState<string | null>(null);

  // Legend-driven state (COMPASS): editable thresholds, per-bucket visibility,
  // neutral-bucket visibility, global layer toggle.
  const [thresholds, setThresholds] = useState<number[]>([
    ...DEFAULT_THRESHOLDS,
  ]);
  const [visibleBuckets, setVisibleBuckets] = useState<Set<number>>(
    () => new Set([0, 1, 2, 3]),
  );
  const [showNeutral, setShowNeutral] = useState(true);
  const [layerVisible, setLayerVisible] = useState(true);

  const mapRef = useRef<maplibregl.Map | null>(null);

  // -------------------------------------------------------------------------
  // Paint overrides + popup renderer.
  // lineColor depends on the editable thresholds -> recomputed on edit, and
  // MapView re-applies it via setPaintProperty (no source rebuild).
  // -------------------------------------------------------------------------
  const paintOverrides = useMemo<MapViewPaintOverrides>(
    () => ({
      lineColor: buildEvolutionColorExpression(thresholds),
      lineWidth: buildEvolutionLineWidthExpression(),
      lineOpacity: buildEvolutionOpacityExpression(),
    }),
    [thresholds],
  );

  // Category visibility filter (drives MapView setFilter).
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
  // Fetch the result GeoJSON (streamed when Content-Length is known).
  // -------------------------------------------------------------------------
  const endpointPath = useMemo(
    () =>
      sessionId
        ? `/api/evolution/result/${encodeURIComponent(sessionId)}`
        : null,
    [sessionId],
  );

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
        const url = `${getApiBase()}${endpointPath}`;
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
        if (reader && total > 0) {
          const chunks: Uint8Array[] = [];
          let received = 0;
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            if (value) {
              chunks.push(value);
              received += value.length;
              setLoadProgress(
                Math.min(99, Math.round((received / total) * 100)),
              );
            }
          }
          if (cancelled) return;
          const blob = new Blob(chunks as BlobPart[], {
            type: "application/json",
          });
          const text = await blob.text();
          const data = JSON.parse(text) as SegmentCollection;
          setGeojson(data);
          setLoadProgress(100);
        } else {
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

    void load();

    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [endpointPath]);

  // -------------------------------------------------------------------------
  // KPIs
  // -------------------------------------------------------------------------
  const kpis = useMemo<EvolutionKpis>(() => {
    if (!geojson) {
      return {
        total: 0,
        hausses: 0,
        baisses: 0,
        significatifs: 0,
        medianJor: null,
      };
    }
    return computeKpis(geojson.features);
  }, [geojson]);

  // Per-bucket counts (and neutral) for the interactive legend — recomputed on
  // threshold edits so the displayed values stay coherent with the coloring.
  const legendCounts = useMemo<{ buckets: number[]; neutral: number }>(() => {
    const buckets = [0, 0, 0, 0];
    let neutral = 0;
    if (geojson) {
      for (const f of geojson.features) {
        const raw = f.properties?.dJOr;
        const idx = bucketIndexOf(raw == null ? null : Number(raw), thresholds);
        if (idx == null) neutral += 1;
        else buckets[idx] += 1;
      }
    }
    return { buckets, neutral };
  }, [geojson, thresholds]);

  // -------------------------------------------------------------------------
  // Search by agregId
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
    const flyDuration = reduced ? 0 : 1200;
    const popupDelay = reduced ? 0 : 1250;

    map.flyTo({
      center: center as [number, number],
      zoom: 16,
      duration: flyDuration,
      essential: true,
    });

    setTimeout(() => {
      const props = (match.properties ?? {}) as GeoJsonProperties;
      const html = renderEvolutionPopup(props);
      new maplibregl.Popup({
        closeButton: true,
        maxWidth: "300px",
        offset: 8,
      })
        .setLngLat(center as [number, number])
        .setHTML(html)
        .addTo(map);
    }, popupDelay);
  }, [geojson, searchValue]);

  // -------------------------------------------------------------------------
  // Download
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

  // -------------------------------------------------------------------------
  // Capture MapView's map instance (same custom-event bridge as /carte)
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
            onClick={() => router.push("/evolution")}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded text-text-muted hover:text-text hover:bg-bg-elevated transition-colors text-xs font-medium cursor-pointer"
            aria-label="Retour a la page Evolution"
          >
            <ArrowLeft size={14} />
            <span>Retour</span>
          </button>

          <div className="hidden sm:block w-px h-5 bg-border" aria-hidden />

          <div className="flex items-baseline gap-2 min-w-0">
            <h1 className="text-sm font-semibold text-text truncate">
              Carte d&apos;evolution — Grand Lyon
            </h1>
            <span className="text-[11px] text-text-muted font-mono truncate hidden md:inline">
              session {sessionId.slice(0, 8)}
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
            icon={<TrendingDown />}
          />
          <KpiCard
            label="Evolution mediane"
            value={fmtPct(kpis.medianJor)}
            icon={<TrendingUp />}
          />
        </div>
      </section>

      {/* Main split : sidebar + map */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0">
        {/* Sidebar */}
        <aside
          className="w-full lg:w-[320px] lg:shrink-0 border-r border-border bg-bg-elevated/40 px-4 py-4 space-y-4 overflow-y-auto"
          aria-label="Recherche et legende"
        >
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

          {/* Tip */}
          <div className="rounded border border-border bg-bg-elevated/50 px-3 py-2.5 text-[10px] text-text-muted leading-relaxed">
            <p>
              <FilterIcon size={10} className="inline -mt-0.5 mr-1" />
              Coloration par dJOr (variation en véh/j) : bleu = baisse, orange =
              hausse (centré sur 0). Les seuils sont modifiables dans la légende.
              Les troncons non significatifs (IC qui se chevauchent) sont
              atténués. Cliquez sur un troncon pour le détail dJOr/JOr/T1/T2.
            </p>
          </div>
        </aside>

        {/* Map */}
        <main
          className="flex-1 min-h-[480px] lg:min-h-0 relative bg-bg-elevated"
          aria-label="Carte interactive de l'evolution des debits"
        >
          {loading && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-bg/70 backdrop-blur-sm">
              <Loader2 className="animate-spin text-accent" size={28} />
              <p className="mt-3 text-xs text-text-muted">
                Chargement de la carte d&apos;evolution...
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

          {!loading && loadError && (
            <div className="absolute inset-0 z-20 flex items-center justify-center p-4">
              <div className="surface-elevated p-5 max-w-sm space-y-3 border-danger/40">
                <div className="flex items-center gap-2 text-danger">
                  <AlertTriangle size={18} />
                  <p className="text-sm font-semibold">
                    Carte d&apos;evolution indisponible
                  </p>
                </div>
                <p className="text-xs text-text-muted">{loadError}</p>
                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => router.push("/evolution")}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-accent text-accent-fg text-xs font-medium hover:bg-indigo-600 cursor-pointer"
                  >
                    Retour generation
                  </button>
                </div>
              </div>
            </div>
          )}

          <MapView
            geojson={geojson}
            theme="dark"
            className="h-full"
            paintOverrides={paintOverrides}
            paintFilter={paintFilter}
            layerVisible={layerVisible}
            renderPopup={renderEvolutionPopup}
            hideDefaultLegend
          />

          {/* Legende divergente interactive specifique evolution */}
          {geojson && (
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
        </main>
      </div>
    </div>
  );
}
