/**
 * kpi.ts — Calcul des KPIs de la page /visualisation (medianes, max, comptages).
 *
 * Extrait de app/visualisation/page.tsx pour decoupler la logique pure de
 * calcul du composant React (cf. boucle d'init de la map qui produisait
 * inline tvrMedian, dplMedian, pmMedian, psMedian, etc.).
 *
 * Cas extremes verifies :
 *   - median([])   -> null
 *   - median([5])  -> 5
 *   - median([1,2,3,4]) -> 2.5  (pair : moyenne des 2 valeurs centrales)
 *   - valeurs NaN/Infinity ignorees (filtrees en amont via isFinite)
 *   - computeKpis({features: []}) -> tous medians a null, tous counts a 0
 */
export interface VisualisationKpis {
  nSegments: number;
  tvrMedian: number | null;
  tvrMax: number | null;
  dplMedian: number | null;
  pmMedian: number | null;
  pmMax: number | null;
  psMedian: number | null;
  psMax: number | null;
  nSegmentsPmPos: number;
  nSegmentsPsPos: number;
  nSensors: number;
  nSegmentsTvrPos: number;
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

/**
 * computeKpis — boucle unique sur les features segments. Calcule en une
 * passe les agreges TVr/DPL/PM/PS (median, max, counts positifs). Le nombre
 * de capteurs est passe separement (peut etre absent du payload segments).
 *
 * Comportement preserve a 100% par rapport a app/visualisation/page.tsx :
 *   - tvrMax exposed seulement si > 0 (sinon null)
 *   - pmMedian/psMedian seulement si pms/pss non vides
 *   - pmMax/psMax exposed seulement si > 0
 *   - nSegmentsTvrPos compte t > 0 (pas t finite, faible difference)
 *   - nSegmentsPmPos compte pm > 0 ET pm finite
 *   - nSegmentsPsPos compte ps > 0 ET ps finite
 */
export function computeKpis(
  features: GeoJSON.Feature[],
  nSensors: number,
): VisualisationKpis {
  const tvrs: number[] = [];
  const dpls: number[] = [];
  const pms: number[] = [];
  const pss: number[] = [];
  let tvrMax = 0;
  let pmMax = 0;
  let psMax = 0;
  let nSegmentsTvrPos = 0;
  let nSegmentsPmPos = 0;
  let nSegmentsPsPos = 0;
  for (const f of features) {
    const t = Number(f.properties?.TVr);
    const d = Number(f.properties?.DPL);
    const pm = Number(f.properties?.PM);
    const ps = Number(f.properties?.PS);
    if (isFinite(t)) {
      tvrs.push(t);
      if (t > tvrMax) tvrMax = t;
      if (t > 0) nSegmentsTvrPos += 1;
    }
    if (isFinite(d)) dpls.push(d);
    if (isFinite(pm) && pm > 0) {
      pms.push(pm);
      if (pm > pmMax) pmMax = pm;
      nSegmentsPmPos += 1;
    }
    if (isFinite(ps) && ps > 0) {
      pss.push(ps);
      if (ps > psMax) psMax = ps;
      nSegmentsPsPos += 1;
    }
  }
  return {
    nSegments: features.length,
    tvrMedian: median(tvrs),
    tvrMax: tvrMax > 0 ? tvrMax : null,
    dplMedian: median(dpls),
    pmMedian: pms.length > 0 ? median(pms) : null,
    pmMax: pmMax > 0 ? pmMax : null,
    psMedian: pss.length > 0 ? median(pss) : null,
    psMax: psMax > 0 ? psMax : null,
    nSegmentsPmPos,
    nSegmentsPsPos,
    nSensors,
    nSegmentsTvrPos,
  };
}

export const EMPTY_KPIS: VisualisationKpis = {
  nSegments: 0,
  tvrMedian: null,
  tvrMax: null,
  dplMedian: null,
  pmMedian: null,
  pmMax: null,
  psMedian: null,
  psMax: null,
  nSegmentsPmPos: 0,
  nSegmentsPsPos: 0,
  nSensors: 0,
  nSegmentsTvrPos: 0,
};
