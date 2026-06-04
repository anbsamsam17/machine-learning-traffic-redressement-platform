/**
 * evolution-palette.ts — palette DIVERGENTE bleu<->orange centree sur 0 pour la
 * carte d'evolution des debits (reference COMPASS).
 *
 * La coloration porte sur la propriete `dJOr` (variation ABSOLUE en veh/j =
 * T2 - T1), et NON sur le pourcentage JOr. Convention :
 *   - bleu  = baisse de trafic (dJOr negatif),
 *   - orange = hausse de trafic (dJOr positif),
 *   - centre = 0.
 *
 * Les bornes sont MODIFIABLES par l'utilisateur (inputs numeriques dans la
 * legende). Par defaut 4 categories separees par 3 seuils [-1000, 0, +1000] :
 *   - dJOr <= -1000 veh/j        -> bleu fonce
 *   - -1000 < dJOr <= 0 veh/j    -> bleu clair
 *   - 0 < dJOr <= +1000 veh/j    -> orange clair
 *   - dJOr > +1000 veh/j         -> orange fonce
 *
 * Les valeurs dJOr null/absentes (categorie evolutif sans delta calculable,
 * troncon nouveau/disparu) tombent dans une categorie NEUTRE grise (non
 * coloree). Les troncons non significatifs (sig=0) sont attenues en opacite.
 */

// ---------------------------------------------------------------------------
// Seuils (editables)
// ---------------------------------------------------------------------------

/**
 * Les 3 bornes par defaut separant les 4 categories de la rampe divergente.
 * MODIFIABLES par l'utilisateur via la legende ; passees a
 * buildEvolutionColorExpression()/buildEvolutionFilter() qui recolorent et
 * refiltrent la carte en consequence.
 */
export const DEFAULT_THRESHOLDS = [-1000, 0, 1000] as const;

/** Nombre de seuils attendus (=> 4 categories). */
export const N_THRESHOLDS = DEFAULT_THRESHOLDS.length;

/** Couleurs des 4 categories de la rampe, du plus bas (baisse) au plus haut. */
export const EVOLUTION_RAMP_COLORS = [
  "#08519c", // bleu fonce  — forte baisse
  "#9ecae1", // bleu clair  — baisse moderee
  "#fdae6b", // orange clair — hausse moderee
  "#d94801", // orange fonce — forte hausse
] as const;

/** Couleur neutre (dJOr null/absent) — non coloree. */
export const EVOLUTION_NEUTRAL_COLOR = "#9ca3af"; // gris

export interface EvolutionBucket {
  /** Index de la categorie (0..3), sert de cle de visibilite/filtre. */
  index: number;
  /** Borne basse exclusive (null = -Infinity). */
  min: number | null;
  /** Borne haute inclusive (null = +Infinity). */
  max: number | null;
  /** Couleur de la categorie. */
  color: string;
  /** Libelle lisible (recalcule a partir des seuils courants). */
  label: string;
}

const NF = new Intl.NumberFormat("fr-FR");

function fmtVeh(n: number): string {
  const sign = n > 0 ? "+" : "";
  return `${sign}${NF.format(n)}`;
}

/**
 * Normalise/ordonne une liste de seuils utilisateur en 3 valeurs croissantes.
 * Tolere des entrees invalides en repliant sur les defauts.
 */
export function normalizeThresholds(input: readonly number[]): number[] {
  const cleaned = input
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v));
  const t =
    cleaned.length === N_THRESHOLDS ? cleaned : [...DEFAULT_THRESHOLDS];
  return t.slice(0, N_THRESHOLDS).sort((a, b) => a - b);
}

/**
 * Derive les 4 categories (couleur + libelle) a partir des seuils courants.
 * thresholds = [t0, t1, t2] croissants.
 */
export function buildBuckets(thresholds: readonly number[]): EvolutionBucket[] {
  const [t0, t1, t2] = normalizeThresholds(thresholds);
  return [
    {
      index: 0,
      min: null,
      max: t0,
      color: EVOLUTION_RAMP_COLORS[0],
      label: `≤ ${fmtVeh(t0)} véh/j`,
    },
    {
      index: 1,
      min: t0,
      max: t1,
      color: EVOLUTION_RAMP_COLORS[1],
      label: `${fmtVeh(t0)} → ${fmtVeh(t1)} véh/j`,
    },
    {
      index: 2,
      min: t1,
      max: t2,
      color: EVOLUTION_RAMP_COLORS[2],
      label: `${fmtVeh(t1)} → ${fmtVeh(t2)} véh/j`,
    },
    {
      index: 3,
      min: t2,
      max: null,
      color: EVOLUTION_RAMP_COLORS[3],
      label: `> ${fmtVeh(t2)} véh/j`,
    },
  ];
}

/** Opacite appliquee selon la significativite (IC disjoints). */
export const SIG_OPACITY = { significant: 0.9, attenuated: 0.3 } as const;

// ---------------------------------------------------------------------------
// Expressions MapLibre
// ---------------------------------------------------------------------------

/** Expression numerique : dJOr coalesce. NaN/null detecte separement. */
function djorExpr(): unknown {
  return ["to-number", ["get", "dJOr"], 0];
}

/** True si dJOr est reellement absent (categorie neutre). */
function djorMissingExpr(): unknown {
  return ["!", ["has", "dJOr"]];
}

/**
 * Expression `line-color` MapLibre, basee sur `dJOr` et les seuils courants :
 *   1. dJOr absent (null/non calculable) -> couleur neutre grise,
 *   2. sinon -> rampe divergente `step` bleu<->orange sur dJOr.
 */
export function buildEvolutionColorExpression(
  thresholds: readonly number[] = DEFAULT_THRESHOLDS,
): unknown[] {
  const [t0, t1, t2] = normalizeThresholds(thresholds);

  // step : [step, input, defaultColor (categorie 0), b1, c1, b2, c2, ...]
  const ramp: unknown[] = [
    "step",
    djorExpr(),
    EVOLUTION_RAMP_COLORS[0],
    t0, EVOLUTION_RAMP_COLORS[1],
    t1, EVOLUTION_RAMP_COLORS[2],
    t2, EVOLUTION_RAMP_COLORS[3],
  ];

  return [
    "case",
    // dJOr absent -> neutre (non colore)
    djorMissingExpr(), EVOLUTION_NEUTRAL_COLOR,
    // rampe divergente
    ramp,
  ];
}

/**
 * Expression `line-opacity` : attenue les troncons non significatifs (sig=0)
 * et conserve la mise en avant au survol. sig absent => traite comme 0.
 */
export function buildEvolutionOpacityExpression(): unknown[] {
  return [
    "case",
    ["boolean", ["feature-state", "hover"], false], 1.0,
    ["==", ["to-number", ["coalesce", ["get", "sig"], 0], 0], 1], SIG_OPACITY.significant,
    SIG_OPACITY.attenuated,
  ];
}

/**
 * Largeur de ligne fonction du zoom uniquement (l'evolution n'a pas de notion
 * de volume sur la geometrie ; on garde une epaisseur lisible et constante par
 * niveau de zoom). Reutilise la meme silhouette que la carte des debits.
 */
export function buildEvolutionLineWidthExpression(): unknown[] {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    8, 1.0,
    13, 2.6,
    17, 5.0,
  ];
}

/**
 * Renvoie l'index de categorie (0..3) d'une valeur dJOr, ou null si absente.
 * Utilise cote JS pour les KPIs et la coherence avec la legende.
 */
export function bucketIndexOf(
  djor: number | null | undefined,
  thresholds: readonly number[] = DEFAULT_THRESHOLDS,
): number | null {
  if (djor == null || !Number.isFinite(djor)) return null;
  const [t0, t1, t2] = normalizeThresholds(thresholds);
  if (djor <= t0) return 0;
  if (djor <= t1) return 1;
  if (djor <= t2) return 2;
  return 3;
}

/**
 * Construit l'expression `filter` MapLibre masquant les categories
 * desactivees. `visible` est un set des index de categorie a afficher (0..3) ;
 * `showNeutral` controle l'affichage des troncons dJOr absent.
 *
 * Renvoie null quand tout est visible (aucun filtre necessaire) afin de ne pas
 * masquer les filtres metier (minTvr, etc.) — ici l'evolution n'en a pas, donc
 * on peut poser directement le filtre de visibilite.
 */
export function buildEvolutionFilter(
  visible: ReadonlySet<number>,
  showNeutral: boolean,
  thresholds: readonly number[] = DEFAULT_THRESHOLDS,
): unknown[] | null {
  const allBucketsVisible = [0, 1, 2, 3].every((i) => visible.has(i));
  if (allBucketsVisible && showNeutral) return null;

  const [t0, t1, t2] = normalizeThresholds(thresholds);
  const d = djorExpr();
  const missing = djorMissingExpr();

  // Conditions par categorie (chaque categorie est un predicat dJOr).
  const bucketCond: Record<number, unknown> = {
    0: ["all", ["!", missing], ["<=", d, t0]],
    1: ["all", ["!", missing], [">", d, t0], ["<=", d, t1]],
    2: ["all", ["!", missing], [">", d, t1], ["<=", d, t2]],
    3: ["all", ["!", missing], [">", d, t2]],
  };

  const anyOf: unknown[] = ["any"];
  for (const i of [0, 1, 2, 3]) {
    if (visible.has(i)) anyOf.push(bucketCond[i]);
  }
  if (showNeutral) anyOf.push(missing);

  // Si rien n'est visible, masquer tout (predicat toujours faux).
  if (anyOf.length === 1) return ["==", 1, 0];
  return anyOf;
}
