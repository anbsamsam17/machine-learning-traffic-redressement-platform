/**
 * palette.ts — Palettes data-viz "neon" + helpers de construction des couches
 * MapLibre superposees (halo / core / shine) pour les visualisations TVr+DPL
 * sur fond de carte satellite (Esri World Imagery).
 *
 * Pourquoi neon ?
 *   Le fond satellite est sombre, texture (vert vegetation, gris voirie, brun
 *   sol nu, blanc toits). Une palette ColorBrewer classique (#fef0d9 -> #7f0000)
 *   se fond dans le bruit. Les hex codes ci-dessous (forte saturation, paliers
 *   chauds + froids divergents) "pop" sur n'importe quelle tuile satellite
 *   tout en restant lisible sur Voyager/Positron/Dark Matter (le switcher
 *   reste fonctionnel).
 *
 * Strategie de rendu en 3 couches (effet "neon glow") :
 *   - halo  : ligne large + line-blur eleve + opacite ~0.5 -> donne la lueur.
 *   - core  : ligne moyenne + opacite 1.0 + line-cap "round" -> la veine
 *             coloree principale (lisible).
 *   - shine : ligne tres fine, presque blanche, opacite ~0.7 -> reflet brillant
 *             (optionnel, automatiquement desactive sur datasets > ~50k features
 *             via `enableShine = false`).
 *
 * Toutes les expressions de paint sont typees `unknown[]` parce que MapLibre
 * accepte des Expression brutes et que TypeScript ne sait pas inferer leur
 * structure recursive. Les call sites doivent caster en `never` au moment de
 * `map.addLayer({...})` (cf. visualisation/page.tsx et discontinuites/page.tsx).
 */

import type maplibregl from "maplibre-gl";

export type Stop = { min: number; color: string };

/**
 * TVr — palette neon CHAUDE (faible -> fort trafic).
 *
 *  0    -> #FFF7CC  jaune pale chaud (visible sur sombre, sans crier)
 *  500  -> #FFDA66  jaune sature
 *  1000 -> #FFA02E  ambre vif
 *  2500 -> #FF6A1F  orange neon
 *  5000 -> #FF3D1F  rouge orange
 *  10000-> #FF1744  rouge neon (signature trafic dense)
 *  20000-> #FF0066  magenta-rouge (pics extremes, "danger")
 *
 * Choix : la fin glisse vers le rose/magenta plutot que le rouge sombre, ce
 * qui se distingue parfaitement de la signaletique satellite (toits rouges
 * naturels ~ #8B3A2A). Tous les hex passent 4.5:1 vs vert vegetation et gris
 * voirie d'apres simulation. Les paliers sont a la fois categoriques
 * (saturation montante) et thermiques (perception "chaud" = densite).
 */
export const TVR_PALETTE_NEON: Stop[] = [
  { min: 0, color: "#FFF7CC" },
  { min: 500, color: "#FFDA66" },
  { min: 1000, color: "#FFA02E" },
  { min: 2500, color: "#FF6A1F" },
  { min: 5000, color: "#FF3D1F" },
  { min: 10000, color: "#FF1744" },
  { min: 20000, color: "#FF0066" },
];

/**
 * DPL — palette neon FROIDE (faible -> fort PL/jour).
 *
 *  0    -> #DCEBFF  bleu glace (presence discrete)
 *  20   -> #7CC4FF  bleu clair sature
 *  50   -> #3A8DFF  bleu vif
 *  100  -> #2A5BFF  bleu indigo electrique
 *  200  -> #5E3DFF  bleu-violet
 *  500  -> #9333EA  violet
 *  1000 -> #C026D3  magenta-violet
 *  2000 -> #FF1FB0  rose neon (PL massifs)
 *
 * Choix : 8 paliers (un de plus que TVr) parce que la distribution DPL est
 * plus etalee en log. Le glissement vers magenta a haut niveau evite le
 * conflit visuel avec le ciel/eau satellite (qui sont aussi bleus). Cette
 * palette n'est *pas* utilisee comme legende "double" avec TVr -- les deux
 * sont toujours montrees separement (toggle TVr/DPL).
 */
export const DPL_PALETTE_NEON: Stop[] = [
  { min: 0, color: "#DCEBFF" },
  { min: 20, color: "#7CC4FF" },
  { min: 50, color: "#3A8DFF" },
  { min: 100, color: "#2A5BFF" },
  { min: 200, color: "#5E3DFF" },
  { min: 500, color: "#9333EA" },
  { min: 1000, color: "#C026D3" },
  { min: 2000, color: "#FF1FB0" },
];

/**
 * Construit l'expression `step` de coloration MapLibre a partir d'une serie
 * de paliers (Stop[]) et d'un champ numerique (TVr/DPL/...).
 *
 * Garantie monotonie stricte des seuils (sinon MapLibre rejette l'expression).
 */
export function buildStepColorExpr(stops: Stop[], field: string): unknown[] {
  const expr: unknown[] = [
    "step",
    ["to-number", ["get", field], 0],
    stops[0].color,
  ];
  let prev = -Infinity;
  for (let i = 1; i < stops.length; i += 1) {
    let v = Number.isFinite(stops[i].min) ? stops[i].min : prev + 1;
    if (v <= prev) v = prev + 1;
    expr.push(v, stops[i].color);
    prev = v;
  }
  return expr;
}

/**
 * Largeur de trait recommandee par zoom pour un contexte urbain (zoom 11 = ville,
 * 14 = quartier, 16 = rue).
 *
 * Triple couche neon : la couche `halo` est ~3x plus large que `core` ; `shine`
 * est ~0.4x. Les paliers ci-dessous sont calibres pour rester lisibles sur
 * satellite a partir de z=11 (sans masquer le reseau routier ambiant).
 */
type LineWidthExpr = unknown[];

function widthCore(): LineWidthExpr {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    9, 1.0,
    11, 2.0,
    13, 3.5,
    14, 4.5,
    16, 6.5,
  ];
}

function widthHalo(): LineWidthExpr {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    9, 3.0,
    11, 6.0,
    13, 10.0,
    14, 12.0,
    16, 16.0,
  ];
}

function widthShine(): LineWidthExpr {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    9, 0.4,
    11, 0.8,
    13, 1.2,
    14, 1.4,
    16, 1.8,
  ];
}

/**
 * Offset lateral data-driven pour separer visuellement les segments bi-directionnels.
 *
 * Le format HERE produit deux features distinctes par troncon physique :
 *   - agregId se terminant par "-F" : sens From -> To
 *   - agregId se terminant par "-T" : sens To -> From
 * Les deux partagent la MEME geometrie LineString MAIS leurs coordonnees sont
 * stockees en SENS INVERSE l'une de l'autre (le -T est le -F lu a l'envers).
 *
 * Subtilite cruciale : `line-offset` de MapLibre applique le decalage
 * perpendiculairement a la direction interne du LineString. Comme F et T ont
 * des directions internes opposees, un MEME signe d'offset (+1 pour les deux)
 * produit des decalages physiques OPPOSES a l'ecran -> F va d'un cote, T va de
 * l'autre, ils deviennent visibles cote a cote.
 *
 * /!\ Erreur classique : utiliser des signes opposes (F:+1, T:-1) les remet
 * du MEME cote physique (les deux negations se compensent) et le -T cache le -F.
 *
 * Les features sans suffixe -F/-T (agregId numerique ou compose) restent a
 * offset = 0 (comportement neutre).
 *
 * Zoom-aware : l'offset croit avec le zoom pour rester visuellement "parallel"
 * sans devorer les rues etroites a faible zoom.
 *
 *   z = 10 : 1 px  (apercu, peu de detail)
 *   z = 14 : 3 px  (quartier, sens clairement separes)
 *   z = 18 : 6 px  (rue, debit visible cote droit / gauche)
 *
 * Garantie : applique de maniere COHERENTE aux 3 couches halo/core/shine
 * sinon le tube neon se desaligne. Centralise ici (helper) plutot que duplique
 * dans chaque buildNeonLineLayers().
 */
export function bidirOffsetExpr(): unknown[] {
  // Meme signe pour F et T : avec leurs coords inversees, l'offset
  // perpendiculaire au LineString interne se traduit par des cotes physiques
  // opposes a l'ecran. Voir le bloc de doc ci-dessus pour la subtilite.
  const dirSign = [
    "case",
    [
      "any",
      ["==", ["slice", ["get", "agregId"], -2], "-F"],
      ["==", ["slice", ["get", "agregId"], -2], "-T"],
    ],
    1,
    0,
  ];
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    10, ["*", dirSign, 1],
    14, ["*", dirSign, 3],
    18, ["*", dirSign, 6],
  ];
}

/**
 * Specification d'une couche neon, pour `map.addLayer(...)`.
 *
 * On retourne un type "souple" : MapLibre accepte des Expression imbriquees
 * que TypeScript ne peut pas typer finement.
 */
export interface NeonLayerSpec {
  id: string;
  type: "line";
  source: string;
  layout: {
    "line-cap": "round";
    "line-join": "round";
    visibility?: "visible" | "none";
  };
  paint: Record<string, unknown>;
}

export interface BuildNeonLayersOptions {
  /** Source MapLibre deja installee dans la pile. */
  sourceId: string;
  /** Prefixe d'id des layers (ex. "segments", "preview-segments"). */
  idPrefix: string;
  /** Champ numerique a colorer (ex. "TVr", "DPL"). */
  field: string;
  /** Paliers de couleurs (defaut : TVR_PALETTE_NEON / DPL_PALETTE_NEON). */
  stops: Stop[];
  /** Visibilite initiale (ex. cachee si on a un toggle TVr/DPL). */
  visibility?: "visible" | "none";
  /** Active la 3e couche "shine" (reflet blanc) -- desactiver si > 50k features
   *  pour preserver le FPS GPU. */
  enableShine?: boolean;
  /** Expression d'opacite custom pour la couche `core` (ex. feature-state hover). */
  coreOpacityExpr?: unknown;
}

/**
 * Construit les 2 ou 3 specs de couches neon (halo / core [+ shine]) pour une
 * source ligne deja existante. L'appelant doit boucler et call `map.addLayer(spec)`.
 *
 * Ordre d'ajout *imperatif* : halo D'ABORD (dessous), puis core, puis shine.
 *
 *   halo  ----  line-blur 4-6, opacity 0.55, width x3
 *   core  ====  opacity 1.0, width x1   <- la veine principale
 *   shine ----  blanc ~0.7, width x0.4  <- reflet (optionnel)
 *
 * Resultat visuel : tube lumineux qui survit a la texture satellite.
 */
export function buildNeonLineLayers(
  opts: BuildNeonLayersOptions,
): NeonLayerSpec[] {
  const {
    sourceId,
    idPrefix,
    field,
    stops,
    visibility,
    enableShine = true,
    coreOpacityExpr,
  } = opts;

  const colorExpr = buildStepColorExpr(stops, field);
  // Offset lateral data-driven pour separer F (sens +) / T (sens -). Calcule
  // une fois et reutilise sur les 3 couches : indispensable que halo + core +
  // shine partagent EXACTEMENT le meme decalage, sinon le tube neon se
  // dedouble visuellement.
  const offsetExpr = bidirOffsetExpr();

  const layers: NeonLayerSpec[] = [];

  // 1) Halo : gros trait flou, opacite modeste. Donne la lueur.
  layers.push({
    id: `${idPrefix}-halo`,
    type: "line",
    source: sourceId,
    layout: {
      "line-cap": "round",
      "line-join": "round",
      ...(visibility ? { visibility } : {}),
    },
    paint: {
      "line-color": colorExpr,
      "line-width": widthHalo(),
      "line-blur": 4,
      "line-opacity": 0.55,
      "line-offset": offsetExpr,
    },
  });

  // 2) Core : la veine coloree principale, parfaitement nette.
  layers.push({
    id: `${idPrefix}-core`,
    type: "line",
    source: sourceId,
    layout: {
      "line-cap": "round",
      "line-join": "round",
      ...(visibility ? { visibility } : {}),
    },
    paint: {
      "line-color": colorExpr,
      "line-width": widthCore(),
      "line-opacity": coreOpacityExpr ?? 1.0,
      "line-offset": offsetExpr,
    },
  });

  // 3) Shine : reflet blanc tres fin (optionnel).
  if (enableShine) {
    layers.push({
      id: `${idPrefix}-shine`,
      type: "line",
      source: sourceId,
      layout: {
        "line-cap": "round",
        "line-join": "round",
        ...(visibility ? { visibility } : {}),
      },
      paint: {
        "line-color": "#FFFFFF",
        "line-width": widthShine(),
        "line-opacity": 0.65,
        "line-offset": offsetExpr,
      },
    });
  }

  return layers;
}

/**
 * Helper : applique en une seule passe les 3 layers (halo/core/shine) a la
 * map. Si `beforeLayerId` est fourni, les couches sont inserees DESSOUS cet
 * id (utile pour passer sous les sensors).
 */
export function addNeonLineLayers(
  map: maplibregl.Map,
  opts: BuildNeonLayersOptions,
  beforeLayerId?: string,
): string[] {
  const specs = buildNeonLineLayers(opts);
  for (const spec of specs) {
    if (!map.getLayer(spec.id)) {
      map.addLayer(spec as never, beforeLayerId);
    }
  }
  return specs.map((s) => s.id);
}

/**
 * Helper : met a jour la palette de couleurs sur les 3 couches en une passe
 * (utilise quand l'utilisateur edite les paliers via la legende interactive).
 *
 * Shine reste blanc et n'est pas touche.
 */
export function updateNeonLineColor(
  map: maplibregl.Map,
  idPrefix: string,
  stops: Stop[],
  field: string,
): void {
  const expr = buildStepColorExpr(stops, field);
  for (const suffix of ["halo", "core"]) {
    const id = `${idPrefix}-${suffix}`;
    if (map.getLayer(id)) {
      map.setPaintProperty(id, "line-color", expr as never);
    }
  }
}

/**
 * Helper : applique un filtre commun aux 3 couches (halo/core/shine) — sans
 * dupliquer le code cote pages.
 */
export function setNeonLineFilter(
  map: maplibregl.Map,
  idPrefix: string,
  filter: unknown | null,
): void {
  for (const suffix of ["halo", "core", "shine"]) {
    const id = `${idPrefix}-${suffix}`;
    if (map.getLayer(id)) {
      map.setFilter(id, filter as never);
    }
  }
}

/**
 * Helper : applique une visibility aux 3 couches.
 */
export function setNeonLineVisibility(
  map: maplibregl.Map,
  idPrefix: string,
  visible: boolean,
): void {
  for (const suffix of ["halo", "core", "shine"]) {
    const id = `${idPrefix}-${suffix}`;
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    }
  }
}

/**
 * Helper : supprime les 3 couches (et eventuellement la source) en mode
 * silencieux.
 */
export function removeNeonLineLayers(
  map: maplibregl.Map,
  idPrefix: string,
  alsoRemoveSourceId?: string,
): void {
  for (const suffix of ["shine", "core", "halo"]) {
    const id = `${idPrefix}-${suffix}`;
    try {
      if (map.getLayer(id)) map.removeLayer(id);
    } catch {
      /* ignore */
    }
  }
  if (alsoRemoveSourceId) {
    try {
      if (map.getSource(alsoRemoveSourceId)) {
        map.removeSource(alsoRemoveSourceId);
      }
    } catch {
      /* ignore */
    }
  }
}

/**
 * Met a jour l'opacite "core" (utilise pour le crossfade preview -> reel).
 * Halo et shine suivent en proportions fixes (0.55x et 0.65x respectivement).
 */
export function setNeonLineOpacity(
  map: maplibregl.Map,
  idPrefix: string,
  coreOpacity: number,
): void {
  const haloOp = coreOpacity * 0.55;
  const shineOp = coreOpacity * 0.65;
  if (map.getLayer(`${idPrefix}-halo`)) {
    map.setPaintProperty(`${idPrefix}-halo`, "line-opacity", haloOp);
  }
  if (map.getLayer(`${idPrefix}-core`)) {
    map.setPaintProperty(`${idPrefix}-core`, "line-opacity", coreOpacity);
  }
  if (map.getLayer(`${idPrefix}-shine`)) {
    map.setPaintProperty(`${idPrefix}-shine`, "line-opacity", shineOp);
  }
}
