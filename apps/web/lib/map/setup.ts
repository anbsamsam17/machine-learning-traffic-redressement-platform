/**
 * setup.ts — helpers MapLibre partages (sensors circles, discontinuites
 * node markers, halo discontinuites) extraits des pages /visualisation et
 * /discontinuites pour decharger les "page.tsx" du detail paint expressions.
 *
 * Les expressions sont construites de facon identique a l'original pour
 * preserver le rendu (radius, colors, opacity, line-offset). Les helpers ne
 * font qu'installer les layers : les listeners (click, mousemove) restent
 * geres dans le composant page car ils branchent souvent du state React.
 */

import type maplibregl from "maplibre-gl";

// ---------------------------------------------------------------------------
// Sensors (TV / PL) — utilises par /visualisation
// ---------------------------------------------------------------------------

export interface SensorLayersOptions {
  sourceId: string;
  /** Stroke des cercles (defaut blanc 2px pour pop sur satellite). */
  stroke?: { color: string; width: number };
}

const SENSOR_RADIUS_EXPR: unknown = [
  "interpolate",
  ["linear"],
  ["zoom"],
  9,
  4,
  13,
  8,
  16,
  14,
];

/**
 * Installe deux layers `circle` filtres sur TMJA TV > 0 et TMJA PL > 0.
 * Identifiants fixes : `sensors-tv` et `sensors-pl` (les filtres de
 * visibilite, click handlers, et la page page.tsx s'appuient sur ces IDs).
 */
export function installSensorLayers(
  map: maplibregl.Map,
  opts: SensorLayersOptions,
): void {
  const { sourceId } = opts;
  const stroke = opts.stroke ?? { color: "#ffffff", width: 2 };

  map.addLayer({
    id: "sensors-tv",
    type: "circle",
    source: sourceId,
    filter: [
      ">",
      ["to-number", ["get", "TMJA Tous Vehicules (veh/jour)"], 0],
      0,
    ],
    paint: {
      "circle-radius": SENSOR_RADIUS_EXPR as never,
      "circle-color": "#22d3ee",
      "circle-stroke-color": stroke.color,
      "circle-stroke-width": stroke.width,
      "circle-opacity": 0.95,
    },
  });

  map.addLayer({
    id: "sensors-pl",
    type: "circle",
    source: sourceId,
    filter: [
      ">",
      ["to-number", ["get", "TMJA Poids Lourds (veh/jour)"], 0],
      0,
    ],
    paint: {
      "circle-radius": SENSOR_RADIUS_EXPR as never,
      "circle-color": "#FF1744",
      "circle-stroke-color": stroke.color,
      "circle-stroke-width": stroke.width,
      "circle-opacity": 0.95,
    },
  });
}

// ---------------------------------------------------------------------------
// Discontinuites — node markers (halo + core)
// ---------------------------------------------------------------------------

export type CauseKey =
  | "FCD_TV_cliff"
  | "FCD_PL_cliff"
  | "Coverage_gap"
  | "Distance_anomaly"
  | "RAMP_asymmetry"
  | "ROUNDABOUT_asymmetry"
  | "FC_transition"
  | "Unexplained";

export type TopologyKey = "Bretelle" | "Carrefour" | "Continuite";

/**
 * Construit les expressions de paint (color match + radius + opacity)
 * utilisees par les layers preview ET reels de /discontinuites. Extrait
 * verbatim de la page (cf. buildCausePaintExprs() de l'ancienne version).
 *
 * Radius core : sqrt(ecart)/5 a z=10, /4 a z=13, /3 a z=16, borne 6..22.
 * Radius halo : core + 8/8/10 selon zoom (filtre tier=red en amont).
 * Opacite core : 0.95 si red, 0.7 sinon.
 *
 * Couleurs en paire avec /lib/discontinuites/palette (PALETTE/TOPO_PALETTE
 * cote page : on prefere une fonction parametrable pour ne pas dupliquer
 * les constantes ici).
 */
export function buildCausePaintExprs(
  causeOrder: CauseKey[],
  palette: Record<CauseKey, string>,
  topologyOrder: TopologyKey[],
  topologyPalette: Record<TopologyKey, string>,
) {
  const COLOR_MATCH: unknown[] = ["match", ["get", "principal_cause"]];
  causeOrder.forEach((c) => {
    COLOR_MATCH.push(c, palette[c]);
  });
  COLOR_MATCH.push("#999999");

  const STROKE_COLOR_MATCH: unknown[] = ["match", ["get", "topology"]];
  topologyOrder.forEach((t) => {
    STROKE_COLOR_MATCH.push(t, topologyPalette[t]);
  });
  STROKE_COLOR_MATCH.push("#FFFFFF");

  const RADIUS_EXPR: unknown = [
    "interpolate",
    ["linear"],
    ["zoom"],
    10,
    ["max", 6, ["min", 16, ["/", ["sqrt", ["max", 1, ["get", "ecart"]]], 5]]],
    13,
    ["max", 7, ["min", 18, ["/", ["sqrt", ["max", 1, ["get", "ecart"]]], 4]]],
    16,
    ["max", 8, ["min", 22, ["/", ["sqrt", ["max", 1, ["get", "ecart"]]], 3]]],
  ];

  const RADIUS_HALO_EXPR: unknown = [
    "interpolate",
    ["linear"],
    ["zoom"],
    10,
    [
      "+",
      8,
      ["max", 6, ["min", 16, ["/", ["sqrt", ["max", 1, ["get", "ecart"]]], 5]]],
    ],
    13,
    [
      "+",
      8,
      ["max", 7, ["min", 18, ["/", ["sqrt", ["max", 1, ["get", "ecart"]]], 4]]],
    ],
    16,
    [
      "+",
      10,
      ["max", 8, ["min", 22, ["/", ["sqrt", ["max", 1, ["get", "ecart"]]], 3]]],
    ],
  ];

  const OPACITY_EXPR: unknown = [
    "case",
    ["==", ["get", "tier"], "red"],
    0.95,
    0.7,
  ];

  return {
    COLOR_MATCH,
    STROKE_COLOR_MATCH,
    RADIUS_EXPR,
    RADIUS_HALO_EXPR,
    OPACITY_EXPR,
  };
}

export interface NodeLayersOptions {
  sourceId: string;
  /** Prefix d'ID. "preview-nodes" pour preview, "nodes" pour reel. */
  idPrefix: string;
  exprs: ReturnType<typeof buildCausePaintExprs>;
  /**
   * Si true (defaut pour les noeuds reels), ajoute un binding feature-state
   * "selected" qui muscle le stroke de 3 a 5px. Mettre false pour le preview
   * qui n'a pas d'interaction selection.
   */
  selectableStroke?: boolean;
}

/**
 * Installe les deux layers halo (tier=red filter) + core des noeuds
 * discontinuites. Identifiants : `${idPrefix}-halo` et `${idPrefix}-circle`.
 */
export function installNodeMarkers(
  map: maplibregl.Map,
  opts: NodeLayersOptions,
): void {
  const { sourceId, idPrefix, exprs, selectableStroke = true } = opts;
  const {
    COLOR_MATCH,
    RADIUS_EXPR,
    RADIUS_HALO_EXPR,
    OPACITY_EXPR,
  } = exprs;

  // Halo neon (red tier uniquement) : blur + opacite muscles -> lueur
  // visible sur satellite sans devorer la map.
  map.addLayer({
    id: `${idPrefix}-halo`,
    type: "circle",
    source: sourceId,
    filter: ["==", ["get", "tier"], "red"],
    paint: {
      "circle-radius": RADIUS_HALO_EXPR as never,
      "circle-color": COLOR_MATCH as never,
      "circle-opacity": 0.35,
      "circle-blur": 0.6,
      "circle-stroke-width": 0,
    },
  });

  // Core : couleur principal_cause + stroke BLANC epais (3px) pour pop
  // contre satellite et fonds clairs. Optionnel : binding feature-state
  // "selected" -> 5px (utilise sur les noeuds reels, pas en preview).
  const strokeWidth: unknown = selectableStroke
    ? [
        "case",
        ["boolean", ["feature-state", "selected"], false],
        5,
        3,
      ]
    : 3;

  map.addLayer({
    id: `${idPrefix}-circle`,
    type: "circle",
    source: sourceId,
    paint: {
      "circle-radius": RADIUS_EXPR as never,
      "circle-color": COLOR_MATCH as never,
      "circle-opacity": OPACITY_EXPR as never,
      "circle-stroke-color": "#FFFFFF",
      "circle-stroke-width": strokeWidth as never,
      "circle-stroke-opacity": 1.0,
    },
  });
}

/**
 * Retire les layers/source d'une installation `installNodeMarkers`.
 * Safe : silencieux si certains layers/source ne sont pas presents.
 */
export function removeNodeMarkers(
  map: maplibregl.Map,
  idPrefix: string,
  sourceId: string,
): void {
  try {
    if (map.getLayer(`${idPrefix}-circle`)) {
      map.removeLayer(`${idPrefix}-circle`);
    }
    if (map.getLayer(`${idPrefix}-halo`)) {
      map.removeLayer(`${idPrefix}-halo`);
    }
    if (map.getSource(sourceId)) {
      map.removeSource(sourceId);
    }
  } catch {
    /* ignore */
  }
}
