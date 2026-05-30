/**
 * ft-disambiguate.ts — Disambiguation F/T au click sur les segments bi-directionnels.
 *
 * Probleme : MapLibre `queryRenderedFeatures` (utilise par les events
 * `map.on("click", layerId, handler)`) tient compte du `line-width` mais
 * IGNORE `line-offset`. Quand deux features partagent la meme geometrie (paires
 * `-F` / `-T` du format HERE) et qu'on les a separees visuellement via
 * `line-offset` (cf. `bidirOffsetExpr` dans palette.ts), un click sur la ligne
 * VISUELLE F retourne *les deux* features (F et T) -- car le hit-test se fait
 * sur l'axe central (geometrie brute), pas sur la position visuelle apres
 * offset.
 *
 * Resultat : `e.features[0]` peut etre T alors que l'utilisateur visait F (ou
 * inversement), de maniere arbitraire selon l'ordre de rendu.
 *
 * Solution : pour chaque feature retournee, on estime sa position VISUELLE en
 * pixels ecran (en tenant compte du line-offset applique) et on choisit le
 * feature dont la position visuelle est la plus proche du point cliqué.
 *
 * Algo (O(n_features * n_segments_par_feature)) -- en pratique 2 features F+T,
 * une dizaine de segments chacune -> < 0.2 ms par click. Negligeable.
 *
 *   1. Pour chaque feature :
 *      a. Recupere le suffixe d'agregId (-F / -T) -> dirSign = 1 (cf. palette).
 *      b. Pour chaque segment a->b de la LineString :
 *         - Projette a et b en pixels ecran (map.project).
 *         - Calcule le projete du click sur le segment (clamp parametre t ∈ [0,1]).
 *         - Calcule le vecteur normal gauche (perpendiculaire au tangent).
 *         - Applique l'offset visuel : pos_visuelle = projete + normal * offsetPx * dirSign.
 *         - Distance euclidienne entre pos_visuelle et clickPx.
 *      c. bestDist = min des distances sur tous les segments.
 *   2. Selectionne le feature avec bestDist minimal.
 *   3. Override e.features = [winner] avant de propager au handler.
 *
 * NB : la cle est que F et T ont leur LineString stocke en sens INVERSE l'un
 * de l'autre dans le format HERE. Du coup, leur vecteur normal gauche pointe
 * dans des sens opposes a l'ecran, et un meme `dirSign = +1` produit des
 * positions visuelles aux cotes opposes physiquement. Cette implementation
 * reflete fidelement ce que MapLibre fait au rendu.
 */

import type maplibregl from "maplibre-gl";

/**
 * Calcule l'offset visuel (en pixels) applique par `bidirOffsetExpr` au zoom
 * courant. Interpole lineairement entre les 3 paliers (z=10 -> 1, z=14 -> 3,
 * z=18 -> 6) -- doit rester aligne avec l'expression MapLibre dans palette.ts.
 */
export function computeOffsetForZoom(zoom: number): number {
  if (zoom <= 10) return 1;
  if (zoom >= 18) return 6;
  if (zoom <= 14) {
    // z=10 -> 1, z=14 -> 3 : pente = (3-1)/(14-10) = 0.5
    return 1 + (zoom - 10) * 0.5;
  }
  // z=14 -> 3, z=18 -> 6 : pente = (6-3)/(18-14) = 0.75
  return 3 + (zoom - 14) * 0.75;
}

/**
 * Type minimal de l'event MapLibre auquel on s'attend. Compatible avec les
 * 2 signatures :
 *   - `map.on("click", layerId, handler)` -> e a `features?: MapGeoJSONFeature[]`
 *   - autres events delegues.
 */
type ClickEventLike = maplibregl.MapMouseEvent & {
  features?: maplibregl.MapGeoJSONFeature[];
};

/**
 * Inspecte le suffixe d'agregId pour determiner si le feature appartient a
 * une paire F/T (et donc subit un offset visuel).
 *
 * Retourne 1 si oui (meme signe pour F et T -- cf. palette.ts), 0 sinon.
 */
function dirSignForFeature(feature: maplibregl.MapGeoJSONFeature): number {
  const agregId = String(feature.properties?.agregId ?? "");
  if (agregId.length < 2) return 0;
  const suffix = agregId.slice(-2);
  return suffix === "-F" || suffix === "-T" ? 1 : 0;
}

/**
 * Itere sur les segments d'un LineString (ou du premier segment d'un
 * MultiLineString) et calcule la distance minimale entre la position
 * visuelle (geometrie + offset perpendiculaire) et le point cliqué.
 *
 * Retourne `Infinity` si la geometrie n'est pas exploitable.
 */
function visualDistanceToClick(
  map: maplibregl.Map,
  feature: maplibregl.MapGeoJSONFeature,
  clickPx: { x: number; y: number },
  offsetPx: number,
  dirSign: number,
): number {
  const geom = feature.geometry as GeoJSON.Geometry;
  let coords: number[][] | null = null;
  if (geom.type === "LineString") {
    coords = geom.coordinates as number[][];
  } else if (geom.type === "MultiLineString") {
    // On considere uniquement le premier segment du MultiLineString : les
    // segments HERE sont des LineString simples en pratique ; le fallback
    // MultiLineString est defensif.
    const ml = geom.coordinates as number[][][];
    coords = ml.length > 0 ? ml[0] : null;
  }
  if (!coords || coords.length < 2) return Infinity;

  let bestDist = Infinity;
  for (let i = 0; i < coords.length - 1; i += 1) {
    const ca = coords[i];
    const cb = coords[i + 1];
    if (!ca || !cb || ca.length < 2 || cb.length < 2) continue;
    const a = map.project([Number(ca[0]), Number(ca[1])]);
    const b = map.project([Number(cb[0]), Number(cb[1])]);
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const lenSq = dx * dx + dy * dy;
    if (lenSq === 0) continue;
    // Parametre du projete orthogonal du click sur le segment ab, clampe [0,1].
    let t = ((clickPx.x - a.x) * dx + (clickPx.y - a.y) * dy) / lenSq;
    if (t < 0) t = 0;
    else if (t > 1) t = 1;
    const projX = a.x + t * dx;
    const projY = a.y + t * dy;
    // Tangent normalise -> normal gauche (rotation 90deg : (-ty, tx)).
    const len = Math.sqrt(lenSq);
    const tx = dx / len;
    const ty = dy / len;
    const nx = -ty;
    const ny = tx;
    // Position visuelle apres application du line-offset (en pixels ecran).
    const visualX = projX + nx * offsetPx * dirSign;
    const visualY = projY + ny * offsetPx * dirSign;
    const ddx = visualX - clickPx.x;
    const ddy = visualY - clickPx.y;
    const d = Math.sqrt(ddx * ddx + ddy * ddy);
    if (d < bestDist) bestDist = d;
  }
  return bestDist;
}

/**
 * Disambiguation F/T : ne garde dans `e.features` que le feature dont la
 * position visuelle (post line-offset) est la plus proche du point cliqué.
 *
 * - Aucun effet si 0 ou 1 feature (cas normaux : pas d'ambiguite).
 * - Aucun effet si aucun feature n'appartient a une paire F/T (dirSign = 0).
 * - Mutation in-place de `e.features` pour preserver la signature attendue
 *   par les handlers existants (typage MapLibre).
 *
 * Complexite : O(n_features * n_segments_par_feature). En pratique
 * < 0.2 ms / click meme sur 100k features (chaque click ne retourne que les
 * features sous le pointeur, generalement 1-3).
 */
export function disambiguateFTClick(
  map: maplibregl.Map,
  e: ClickEventLike,
): ClickEventLike {
  const features = e.features;
  if (!features || features.length <= 1) return e;

  const clickPx = e.point;
  const zoom = map.getZoom();
  const offsetPx = computeOffsetForZoom(zoom);

  let bestIdx = -1;
  let bestDist = Infinity;
  let foundAnyFT = false;
  for (let i = 0; i < features.length; i += 1) {
    const f = features[i];
    const dirSign = dirSignForFeature(f);
    if (dirSign === 0) continue;
    foundAnyFT = true;
    const d = visualDistanceToClick(map, f, clickPx, offsetPx, dirSign);
    if (d < bestDist) {
      bestDist = d;
      bestIdx = i;
    }
  }
  // Pas de paire F/T detectee -> on laisse l'event original (rien a faire).
  if (!foundAnyFT || bestIdx < 0) return e;

  // Override : ne garde que le feature gagnant. On mute in-place pour rester
  // compatible avec les handlers qui lisent e.features apres coup.
  e.features = [features[bestIdx]];
  return e;
}
