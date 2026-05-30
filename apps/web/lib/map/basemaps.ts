/**
 * basemaps.ts — Catalogue centralise des fonds de carte raster utilises par
 * MapLibre dans toute l'application (modules /visualisation et /discontinuites).
 *
 * Tous les fournisseurs sont GRATUITS et sans cle API :
 *   - Carto Voyager     -> clair moderne (defaut, equilibre couleurs/lisibilite)
 *   - Carto Positron    -> clair neutre, tres epure
 *   - Carto Dark Matter -> sombre, contraste eleve pour visualisations data
 *   - Esri World Imagery -> tuiles satellite (ordre {z}/{y}/{x} specifique)
 *
 * IMPORTANT : pour le switch dynamique, on utilise
 *   (map.getSource("carto") as maplibregl.RasterTileSource).setTiles([...])
 * Cette approche prserve toutes les overlays (sources data, layers metiers)
 * et evite un setStyle() qui re-creerait toute la pile.
 */

export type BasemapId = "voyager" | "positron" | "dark" | "satellite";

export interface BasemapDef {
  id: BasemapId;
  label: string;
  /** Sous-titre court pour le panneau du switcher. */
  description: string;
  /** URLs des tuiles (multi-sous-domaines pour Carto). */
  tiles: string[];
  /** Attribution HTML conforme aux conditions des fournisseurs. */
  attribution: string;
  /** Thumbnail couleur dominante (utilise pour le mini-aperu visuel). */
  thumb: {
    /** Gradient CSS de la vignette (rendu via background-image). */
    background: string;
    /** Bordure de la vignette. */
    border: string;
  };
}

const CARTO_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>';

const ESRI_ATTRIBUTION =
  'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics';

// Carto subdomains a/b/c/d, retina @2x for sharper rendering.
function carto(tileset: string): string[] {
  return ["a", "b", "c", "d"].map(
    (s) => `https://${s}.basemaps.cartocdn.com/${tileset}/{z}/{x}/{y}@2x.png`,
  );
}

export const BASEMAPS: Record<BasemapId, BasemapDef> = {
  voyager: {
    id: "voyager",
    label: "Clair",
    description: "Carto Voyager",
    tiles: carto("rastertiles/voyager"),
    attribution: CARTO_ATTRIBUTION,
    thumb: {
      background:
        "linear-gradient(135deg, #f5f1e8 0%, #e8e0d2 45%, #d4cab8 100%)",
      border: "rgba(0,0,0,.10)",
    },
  },
  positron: {
    id: "positron",
    label: "Epure",
    description: "Carto Positron",
    tiles: carto("light_all"),
    attribution: CARTO_ATTRIBUTION,
    thumb: {
      background:
        "linear-gradient(135deg, #fafafa 0%, #ececec 50%, #d8d8d8 100%)",
      border: "rgba(0,0,0,.10)",
    },
  },
  dark: {
    id: "dark",
    label: "Sombre",
    description: "Carto Dark Matter",
    tiles: carto("dark_all"),
    attribution: CARTO_ATTRIBUTION,
    thumb: {
      background:
        "linear-gradient(135deg, #1a1a1a 0%, #0d0d0d 50%, #000000 100%)",
      border: "rgba(255,255,255,.15)",
    },
  },
  satellite: {
    id: "satellite",
    // Esri specific: {z}/{y}/{x} order (NOT {z}/{x}/{y}).
    label: "Satellite",
    description: "Esri World Imagery",
    tiles: [
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    ],
    attribution: ESRI_ATTRIBUTION,
    thumb: {
      background:
        "linear-gradient(135deg, #3c5b3a 0%, #2d4530 35%, #5b6f4a 70%, #8a8769 100%)",
      border: "rgba(255,255,255,.15)",
    },
  },
};

/** Fond de carte par defaut : satellite (Esri World Imagery).
 *  Choix data-viz : contraste maximal pour les segments neon (TVr/DPL) et les
 *  noeuds de discontinuites avec halo + stroke blanc. L'utilisateur peut
 *  basculer via <BasemapSwitcher /> et sa preference est persistee. */
export const DEFAULT_BASEMAP: BasemapId = "satellite";

/** Cle utilisee pour memoriser la preference dans localStorage. */
export const BASEMAP_STORAGE_KEY = "mdl_basemap_preference";

/** Liste ordonnee pour l'affichage dans le switcher. */
export const BASEMAP_ORDER: BasemapId[] = [
  "voyager",
  "positron",
  "dark",
  "satellite",
];

/**
 * Lit la preference utilisateur depuis localStorage (SSR-safe).
 * Retourne DEFAULT_BASEMAP si pas de storage ou valeur invalide.
 */
export function readStoredBasemap(): BasemapId {
  if (typeof window === "undefined") return DEFAULT_BASEMAP;
  try {
    const raw = window.localStorage.getItem(BASEMAP_STORAGE_KEY);
    if (raw && raw in BASEMAPS) return raw as BasemapId;
  } catch {
    /* localStorage indispo (mode privacy strict) -> fallback silencieux */
  }
  return DEFAULT_BASEMAP;
}

/** Persiste la preference utilisateur (no-op cote SSR). */
export function writeStoredBasemap(id: BasemapId): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(BASEMAP_STORAGE_KEY, id);
  } catch {
    /* ignore quota / privacy mode */
  }
}
