"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  FeatureCollection,
  LineString,
  GeoJsonProperties,
} from "geojson";
import maplibregl, { type Map as MlMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { getMapStyle } from "@/lib/map-style";
import {
  buildTvrStepExpression,
  buildLineWidthExpression,
} from "@/lib/map-palette";
import { Legend } from "./Legend";
import { renderPopupHTML, POPUP_CSS } from "./MapPopup";

const SOURCE_ID = "carte-segments";
const LAYER_ID = "carte-segments-line";
const HOVER_LAYER_ID = "carte-segments-hover";

export interface MapViewFilters {
  /** Minimum TVr to display (segments with TVr < this are filtered out). */
  minTvr?: number;
  /** Exclude FC = 1 (motorways) when true. */
  excludeFc1?: boolean;
}

export interface MapViewProps {
  /** GeoJSON returned by /api/carte/generate. */
  geojson: FeatureCollection<LineString, GeoJsonProperties> | null;
  filters?: MapViewFilters;
  /** Theme override; defaults to the page theme. */
  theme?: "dark" | "light";
  className?: string;
}

/**
 * MapView — Maplibre client wrapper that:
 *  - mounts a basemap (Carto Dark Matter / Voyager) once,
 *  - swaps the style when the theme changes,
 *  - loads the carte GeoJSON as a single source + LineLayer (12k+ segments OK),
 *  - applies a graduated palette on `TVr` via `step` paint expression,
 *  - highlights hovered segment + opens a popup on click,
 *  - auto-fits to the data bbox on first load,
 *  - applies user filters via `setFilter` (no source rebuild).
 */
export function MapView({
  geojson,
  filters,
  theme = "dark",
  className = "",
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const hoveredIdRef = useRef<string | number | null>(null);
  const lastFitGeoJsonRef = useRef<FeatureCollection | null>(null);
  const [styleLoaded, setStyleLoaded] = useState(false);

  // Honor prefers-reduced-motion: shorter / instant transitions
  const reducedMotion = useMemo(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  }, []);

  // ---------------------------------------------------------------------------
  // One-time init
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: getMapStyle(theme),
      center: [2.35, 46.8], // France
      zoom: 5,
      attributionControl: { compact: true },
      // Use canvas2d to render raster basemap consistently across browsers
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      setStyleLoaded(true);
      // Expose the underlying map handle via a custom event so external
      // hosts (e.g. /carte/visualiser/[id] for search → flyTo + popup) can
      // drive the map without props/ref plumbing. Optional consumer — the
      // event is harmless if no one listens.
      try {
        window.dispatchEvent(
          new CustomEvent("carte-map-ready", { detail: { map } }),
        );
      } catch {
        // Old browsers / SSR — ignore.
      }
    });

    // Inject popup CSS once
    if (typeof document !== "undefined" && !document.getElementById("mapview-popup-css")) {
      const styleEl = document.createElement("style");
      styleEl.id = "mapview-popup-css";
      styleEl.textContent = POPUP_CSS;
      document.head.appendChild(styleEl);
    }

    mapRef.current = map;

    return () => {
      try {
        map.remove();
      } catch {
        // ignore
      }
      mapRef.current = null;
      setStyleLoaded(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------------------------------------------------------------------
  // Theme switching — re-apply style and re-add the data source
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleLoaded) return;
    setStyleLoaded(false);
    map.setStyle(getMapStyle(theme));
    map.once("idle", () => setStyleLoaded(true));
  }, [theme]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Source + layer setup (re-runs on every styleLoaded change, including theme)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleLoaded) return;

    const data: FeatureCollection<LineString, GeoJsonProperties> =
      geojson ?? { type: "FeatureCollection", features: [] };

    // Ensure each feature has an id (for hover state via setFeatureState)
    if (!data.features.some((f) => f.id == null)) {
      // already ids present
    } else {
      data.features.forEach((f, i) => {
        if (f.id == null) f.id = i;
      });
    }

    // Add (or update) source
    const existing = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data as unknown as GeoJSON.GeoJSON);
    } else {
      map.addSource(SOURCE_ID, {
        type: "geojson",
        data: data as unknown as GeoJSON.GeoJSON,
        generateId: true,
        // Performance: server-side simplification at low zoom would be nicer,
        // but 12k-15k LineStrings render fine without clustering.
        promoteId: undefined,
      });

      // Main line layer
      map.addLayer({
        id: LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": buildTvrStepExpression() as never,
          "line-width": buildLineWidthExpression() as never,
          "line-opacity": [
            "case",
            ["boolean", ["feature-state", "hover"], false], 1.0,
            0.85,
          ] as never,
        },
      });

      // Transparent hit layer below for easier clicks (extra width)
      map.addLayer(
        {
          id: HOVER_LAYER_ID,
          type: "line",
          source: SOURCE_ID,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#ffffff",
            "line-width": 12,
            "line-opacity": 0,
          },
        },
        LAYER_ID,
      );

      // ----------- Interactions -----------
      map.on("mousemove", HOVER_LAYER_ID, (e) => {
        const f = e.features?.[0];
        if (!f) return;
        if (hoveredIdRef.current != null && hoveredIdRef.current !== f.id) {
          map.setFeatureState(
            { source: SOURCE_ID, id: hoveredIdRef.current },
            { hover: false },
          );
        }
        hoveredIdRef.current = f.id ?? null;
        if (f.id != null) {
          map.setFeatureState({ source: SOURCE_ID, id: f.id }, { hover: true });
        }
        map.getCanvas().style.cursor = "pointer";
      });

      map.on("mouseleave", HOVER_LAYER_ID, () => {
        if (hoveredIdRef.current != null) {
          map.setFeatureState(
            { source: SOURCE_ID, id: hoveredIdRef.current },
            { hover: false },
          );
          hoveredIdRef.current = null;
        }
        map.getCanvas().style.cursor = "";
      });

      map.on("click", HOVER_LAYER_ID, (e) => {
        const f = e.features?.[0];
        if (!f) return;
        new maplibregl.Popup({
          closeButton: true,
          maxWidth: "280px",
          offset: 8,
        })
          .setLngLat(e.lngLat)
          .setHTML(renderPopupHTML(f.properties))
          .addTo(map);
      });
    }

    // ----------- Bbox fit (only when geojson identity changed) -----------
    if (data.features.length > 0 && lastFitGeoJsonRef.current !== geojson) {
      const bbox = computeBbox(data);
      if (bbox) {
        map.fitBounds(
          [
            [bbox[0], bbox[1]],
            [bbox[2], bbox[3]],
          ],
          {
            padding: 60,
            maxZoom: 14,
            duration: reducedMotion ? 0 : 800,
          },
        );
      }
      lastFitGeoJsonRef.current = geojson;
    }
  }, [geojson, styleLoaded, reducedMotion]);

  // ---------------------------------------------------------------------------
  // Filters — runtime setFilter
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleLoaded || !map.getLayer(LAYER_ID)) return;

    const conditions: unknown[] = ["all"];
    if (filters?.minTvr && filters.minTvr > 0) {
      // Output GeoJSON expose `JOr` (rename TVr->JOr cascade complet,
      // cf carte.py changement 4). Coalesce avec `TVr` pour compat
      // avec d'eventuels GeoJSON historiques.
      conditions.push([">=", ["to-number", ["coalesce", ["get", "JOr"], ["get", "TVr"]], 0], filters.minTvr]);
    }
    if (filters?.excludeFc1) {
      conditions.push(["!=", ["to-number", ["get", "FC"], 0], 1]);
    }
    const expr = conditions.length === 1 ? null : (conditions as never);
    map.setFilter(LAYER_ID, expr);
    map.setFilter(HOVER_LAYER_ID, expr);
  }, [filters?.minTvr, filters?.excludeFc1, styleLoaded]);

  return (
    <div className={`relative w-full h-full ${className}`}>
      <div
        ref={containerRef}
        className="absolute inset-0 rounded-xl overflow-hidden"
        role="region"
        aria-label="Carte interactive des débits"
      />

      {!geojson && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="rounded-xl border border-white/10 bg-[rgba(15,20,40,0.9)] backdrop-blur px-5 py-4 text-center max-w-sm">
            <p className="text-xs text-slate-300">
              Aucune carte chargée. Renseignez les modèles et le fichier FCD,
              puis lancez la génération pour afficher les tronçons.
            </p>
          </div>
        </div>
      )}

      {geojson && <Legend />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

/**
 * Cheap bbox over a FeatureCollection of LineStrings.
 * Avoids pulling in @turf/bbox (~250kb) just for this.
 */
function computeBbox(
  fc: FeatureCollection<LineString, GeoJsonProperties>,
): [number, number, number, number] | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let found = false;

  for (const feat of fc.features) {
    const coords = feat.geometry?.coordinates;
    if (!coords) continue;
    for (const [x, y] of coords) {
      if (typeof x !== "number" || typeof y !== "number") continue;
      if (!isFinite(x) || !isFinite(y)) continue;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
      found = true;
    }
  }
  return found ? [minX, minY, maxX, maxY] : null;
}
