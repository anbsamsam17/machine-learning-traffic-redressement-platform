"use client";

/**
 * use-map-instance — hook React partage pour instancier MapLibre.
 *
 * Factorise l'init MapLibre + controle navigation + scale + lecture du
 * basemap stocke en localStorage. Aujourd'hui utilise par /visualisation et
 * /discontinuites pour eviter la duplication de la boucle d'init dans deux
 * useEffect (~70 lignes chacune).
 *
 * Le composant appelant reste responsable de :
 *  - Definir les sources/layers une fois la map prete (via onReady ou en
 *    surveillant `ready`).
 *  - Installer les listeners (click, mousemove, ...) sur ses propres layers.
 *  - Injecter les <style> CSS pour les popups/attribution (pas de side effect
 *    automatique ici pour ne pas creer de couplage avec un design system
 *    specifique a une page).
 */

import { useEffect, useRef, useState, type RefObject } from "react";
import maplibregl from "maplibre-gl";
import { BASEMAPS, readStoredBasemap } from "@/lib/map/basemaps";

export interface UseMapInstanceOptions {
  /** Ref vers le container <div> qui accueillera le canvas. */
  containerRef: RefObject<HTMLDivElement | null>;
  /** Position initiale [lng, lat]. */
  center: [number, number];
  /** Zoom initial. */
  zoom: number;
  /**
   * Position du NavigationControl (zoom in/out + boussole).
   * Defaut "top-right". Mettre `null` pour ne pas l'ajouter.
   */
  navigationPosition?: "top-right" | "top-left" | "bottom-right" | "bottom-left" | null;
  /**
   * Position du ScaleControl (echelle metrique).
   * Defaut "bottom-left". Mettre `null` pour ne pas l'ajouter.
   */
  scalePosition?: "top-right" | "top-left" | "bottom-right" | "bottom-left" | null;
  /** Active a "load". Permet d'enchainer immediatement avec addSource/addLayer. */
  onReady?: (map: maplibregl.Map) => void;
  /**
   * Si renseigne, expose la map sur window[devGlobalName] en dev pour debug
   * console. Garde uniquement quand process.env.NODE_ENV === "development".
   */
  devGlobalName?: string;
  /**
   * Active : si false, le hook n'instancie pas la map. Utile pour les pages
   * qui ont besoin d'attendre une etape (ex: hydration gate sur
   * /discontinuites).
   */
  enabled?: boolean;
}

export interface UseMapInstanceResult {
  /** Instance MapLibre courante. null avant le mount ou apres le cleanup. */
  map: maplibregl.Map | null;
  /** Passe a true au "load" MapLibre. Reset a false au cleanup/unmount. */
  ready: boolean;
}

/**
 * Instancie MapLibre dans le container, le retire au unmount.
 *
 * Ne re-instancie PAS quand `center`/`zoom`/`onReady` changent : le hook
 * s'execute une seule fois (dependances volontairement statiques). Si on a
 * besoin de re-centrer, utiliser `map.flyTo({...})` apres `ready === true`.
 */
export function useMapInstance(
  opts: UseMapInstanceOptions,
): UseMapInstanceResult {
  const {
    containerRef,
    center,
    zoom,
    navigationPosition = "top-right",
    scalePosition = "bottom-left",
    onReady,
    devGlobalName,
    enabled = true,
  } = opts;

  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);

  // Capture des callbacks pour qu'ils restent stables vis-a-vis du useEffect
  // (le hook ne doit pas re-instancier MapLibre quand le caller passe une
  // nouvelle reference onReady inline).
  const onReadyRef = useRef(onReady);
  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  useEffect(() => {
    if (!enabled) return;
    if (!containerRef.current || mapRef.current) return;

    const initialBasemap = BASEMAPS[readStoredBasemap()];

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          carto: {
            type: "raster",
            tiles: initialBasemap.tiles,
            tileSize: 256,
            attribution: initialBasemap.attribution,
            maxzoom: 19,
          },
        },
        layers: [{ id: "carto", type: "raster", source: "carto" }],
      },
      center,
      zoom,
      hash: false,
      attributionControl: { compact: true },
    });

    if (navigationPosition) {
      map.addControl(
        new maplibregl.NavigationControl({ visualizePitch: false }),
        navigationPosition,
      );
    }
    if (scalePosition) {
      map.addControl(
        new maplibregl.ScaleControl({ unit: "metric" }),
        scalePosition,
      );
    }

    map.on("load", () => {
      setReady(true);
      onReadyRef.current?.(map);
    });

    mapRef.current = map;

    if (
      devGlobalName &&
      process.env.NODE_ENV === "development" &&
      typeof window !== "undefined"
    ) {
      (window as unknown as Record<string, unknown>)[devGlobalName] = map;
    }

    return () => {
      try {
        map.remove();
      } catch {
        /* ignore */
      }
      mapRef.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return { map: mapRef.current, ready };
}
