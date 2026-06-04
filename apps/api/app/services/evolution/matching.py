"""Appariement de troncons entre deux cartes de debits (T1 -> base T2).

Portage GENERIQUE du pipeline de production ``FCDREFGLOBAL`` (etapes 01/02/03/05/07)
au contexte evolution : on apparie chaque troncon de la BASE T2 (annee2, le plus
dense) a son homologue T1 (annee1), car la sortie est par troncon T2.

3 niveaux d'appariement (interface unique ``match_segments``) :

* N1 - CLE EXACTE : jointure par ``agregId`` exact (suffixe -F/-T inclus).
  -> ``match_level=CLE``, ``match_score=None``.
* N2 - MAP-MATCHING GEOMETRIQUE pour les troncons base T2 non apparies en N1 :
  reprojection EPSG:2154, candidats STRtree ``dwithin`` (rayon par FC), gate de
  sens (rejet dur Dtheta>=120 deg), score composite (poids de production), puis
  affectation hongroise (``linear_sum_assignment``) par cluster local pour
  l'unicite. Seuils calibres : GEOM_AUTO (score>=0.6366 & marge>=0.05),
  GEOM_VERIF (0.565<=score<0.6366 ou marge faible), sinon NON_MATCH.
* N3 - VERIFICATION BAN (filtre de securite UNIQUEMENT) : reverse-geocoding des
  points milieux ; un MISMATCH retrograde GEOM_AUTO -> GEOM_VERIF. BAN ne
  promeut JAMAIS un appariement.

Aucune metrique de debit (JOr volume) n'intervient ici : le matching est purement
geometrique, independant de l'annee. Le calcul d'evolution est dans ``compute``.
"""

from __future__ import annotations

import io as _io
import logging
import re
import time
import unicodedata
from typing import Callable

logger = logging.getLogger(__name__)

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.optimize import linear_sum_assignment
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely import STRtree

# --------------------------------------------------------------------------- #
# CRS
# --------------------------------------------------------------------------- #
CRS_WGS84 = "EPSG:4326"
CRS_L93 = "EPSG:2154"

# --------------------------------------------------------------------------- #
# Parametres de matching (conserves du pipeline de production, cf common.py).
# --------------------------------------------------------------------------- #
RADIUS_BY_FC: dict[int, float] = {1: 25.0, 2: 15.0, 3: 15.0, 4: 10.0, 5: 8.0}
RADIUS_DEFAULT = 15.0
BUFFER_HALF_WIDTH = 5.0
FC_TOLERANCE = 1
LEN_RATIO_MIN = 0.05
SCALE_M = 10.0  # echelle de tolerance laterale (s_dist / s_haus)

# Gate de sens / penalite directionnelle (degres).
GATE_HARD_REJECT_DEG = 120.0
DIR_PENALTY_SCALE_DEG = 120.0

# Seuils calibres (etape 04, valides GO).
THR_AUTO = 0.6366
THR_REVIEW = 0.565
MARGIN_MIN = 0.05

# Colonnes de tracabilite de la DataFrame retournee.
RESULT_COLS = ["id_t2", "id_t1", "match_level", "match_score", "ban_concordance"]


def _noop_progress(pct: float, stage: str) -> None:  # pragma: no cover - default
    """Callback de progression par defaut (silencieux)."""
    return None


# --------------------------------------------------------------------------- #
# Azimut moyen circulaire (convention HD du pipeline, est=0, trigo)
# --------------------------------------------------------------------------- #
def line_mean_azimuth_deg(geoms: gpd.GeoSeries) -> np.ndarray:
    """Azimut moyen circulaire de LineStrings, pondere par longueur de segment.

    Convention identique au pipeline de production : ``atan2(dy, dx)`` en degres
    dans [0, 360) (est = 0, sens trigonometrique).
    """
    arr = np.asarray(geoms.values, dtype=object)
    if len(arr) == 0:
        return np.zeros(0, dtype="float64")
    coords = shapely.get_coordinates(arr)
    n_pts = shapely.get_num_coordinates(arr)
    geom_id = np.repeat(np.arange(len(arr)), n_pts)

    dx = np.diff(coords[:, 0])
    dy = np.diff(coords[:, 1])
    same_geom = geom_id[1:] == geom_id[:-1]
    seg_geom = geom_id[1:][same_geom]
    dx = dx[same_geom]
    dy = dy[same_geom]

    seg_len = np.hypot(dx, dy)
    az = np.mod(np.degrees(np.arctan2(dy, dx)), 360.0)
    az_rad = np.radians(az)
    sin_w = np.bincount(seg_geom, weights=seg_len * np.sin(az_rad), minlength=len(arr))
    cos_w = np.bincount(seg_geom, weights=seg_len * np.cos(az_rad), minlength=len(arr))
    return np.mod(np.degrees(np.arctan2(sin_w, cos_w)), 360.0)


def circular_diff_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Ecart angulaire circulaire dans [0, 180] entre deux azimuts (degres)."""
    return np.abs(np.mod(a - b + 180.0, 360.0) - 180.0)


# --------------------------------------------------------------------------- #
# Preparation : reprojection L93 + longueurs + azimut
# --------------------------------------------------------------------------- #
def _prepare_l93(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reprojeter en EPSG:2154 et precalculer longueur, azimut, FC entiere."""
    g = gdf.copy()
    if g.crs is None:
        g = g.set_crs(CRS_WGS84)
    g93 = g.to_crs(CRS_L93)
    length_m = g93.geometry.length.to_numpy()
    g93 = g93.assign(
        length_m=length_m,
        az_line=line_mean_azimuth_deg(g93.geometry),
        fc_int=pd.to_numeric(g93.get("FC"), errors="coerce"),
        geom_ok=(g93.geometry.is_valid.to_numpy() & (length_m > 0)),
    )
    return g93.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# N2.a - Candidats par STRtree dwithin (base T2 = source, T1 = cible)
# --------------------------------------------------------------------------- #
def build_candidates(g_base: gpd.GeoDataFrame, g_t1: gpd.GeoDataFrame) -> pd.DataFrame:
    """Paires candidates (src = troncon base T2 -> tgt = troncon T1).

    STRtree ``dwithin`` au rayon max, puis filtres rayon-par-FC, classe FC (+/-1)
    et ratio de longueurs (permissif).
    """
    geom_b = g_base.geometry.values
    geom_t = g_t1.geometry.values
    if len(geom_b) == 0 or len(geom_t) == 0:
        return pd.DataFrame({"src_idx": [], "tgt_idx": [], "cand_dist_m": []})

    fc_b = g_base["fc_int"].to_numpy().astype("float64")
    fc_t = g_t1["fc_int"].to_numpy().astype("float64")
    len_b = g_base["length_m"].to_numpy()
    len_t = g_t1["length_m"].to_numpy()

    r_max = max(RADIUS_BY_FC.values())
    radius_src = np.array(
        [RADIUS_BY_FC.get(int(f) if np.isfinite(f) else -1, RADIUS_DEFAULT) for f in fc_b]
    )

    tree = STRtree(geom_t)
    src_idx, tgt_idx = tree.query(geom_b, predicate="dwithin", distance=r_max)
    if src_idx.size == 0:
        return pd.DataFrame({"src_idx": [], "tgt_idx": [], "cand_dist_m": []})

    dist = shapely.distance(geom_b[src_idx], geom_t[tgt_idx])
    keep_r = dist <= radius_src[src_idx]
    fc_diff = np.abs(fc_b[src_idx] - fc_t[tgt_idx])
    keep_fc = ~np.isfinite(fc_diff) | (fc_diff <= FC_TOLERANCE)
    l_s, l_t = len_b[src_idx], len_t[tgt_idx]
    lr = np.minimum(l_s, l_t) / np.maximum(np.maximum(l_s, l_t), 1e-9)
    keep_len = lr >= LEN_RATIO_MIN
    keep = keep_r & keep_fc & keep_len

    return pd.DataFrame({
        "src_idx": src_idx[keep].astype("int64"),
        "tgt_idx": tgt_idx[keep].astype("int64"),
        "cand_dist_m": dist[keep].astype("float64"),
    })


# --------------------------------------------------------------------------- #
# N2.b/c - Score composite + gate de sens
# --------------------------------------------------------------------------- #
def score_pairs(
    g_base: gpd.GeoDataFrame,
    g_t1: gpd.GeoDataFrame,
    cand: pd.DataFrame,
    *,
    dtheta_reject: float = GATE_HARD_REJECT_DEG,
    dir_penalty_scale: float = DIR_PENALTY_SCALE_DEG,
) -> pd.DataFrame:
    """Calculer le score composite (poids de production) et le gate de sens.

    Les cartes d'evolution n'ont pas de flags is_roundabout / is_ramp : le gate
    dur est donc actif partout (Dtheta>=120 deg -> rejet), conformement au
    pipeline (qui ne desactive le gate que sur rb/ramp).

    Les seuils de sens (``dtheta_reject``, ``dir_penalty_scale``) sont injectes
    en parametres : aucun etat global n'est lu ni mute (thread-safe).
    """
    if cand.empty:
        return cand.assign(dtheta_deg=[], gate_pass=[], cover_a=[],
                           mean_ptline_m=[], score=[])
    si = cand["src_idx"].to_numpy()
    ti = cand["tgt_idx"].to_numpy()
    n = si.size

    geom_b = g_base.geometry.values
    geom_t = g_t1.geometry.values
    a = geom_b[si]  # base T2
    b = geom_t[ti]  # T1
    len_b = g_base["length_m"].to_numpy()[si]
    len_t = g_t1["length_m"].to_numpy()[ti]

    hw = BUFFER_HALF_WIDTH
    buf_a = shapely.buffer(a, hw, cap_style="flat")
    buf_b = shapely.buffer(b, hw, cap_style="flat")
    area_a = shapely.area(buf_a)
    area_b = shapely.area(buf_b)
    area_i = shapely.area(shapely.intersection(buf_a, buf_b))
    union = area_a + area_b - area_i
    iou = np.where(union > 0, area_i / union, 0.0)
    cover_a = np.where(area_a > 0, area_i / area_a, 0.0)

    n_samp = 11
    fracs = np.linspace(0.0, 1.0, n_samp)
    dist_samples = np.empty((n, n_samp), dtype="float64")
    for j, fr in enumerate(fracs):
        pts = shapely.line_interpolate_point(a, fr, normalized=True)
        dist_samples[:, j] = shapely.distance(pts, b)
    mean_ptline = dist_samples.mean(axis=1)

    hausdorff = shapely.hausdorff_distance(a, b)
    len_ratio = np.minimum(len_b, len_t) / np.maximum(np.maximum(len_b, len_t), 1e-9)

    az_b = g_base["az_line"].to_numpy()[si]
    az_t = g_t1["az_line"].to_numpy()[ti]
    dtheta = circular_diff_deg(az_b, az_t)
    gate_pass = dtheta < dtheta_reject

    s_dist = np.exp(-mean_ptline / SCALE_M)
    s_haus = np.exp(-hausdorff / (3.0 * SCALE_M))
    s_dir = np.clip(1.0 - dtheta / 90.0, 0.0, 1.0)
    score_base = (
        0.28 * iou + 0.18 * cover_a + 0.16 * s_dist
        + 0.08 * s_haus + 0.08 * len_ratio + 0.22 * s_dir
    )
    fac = np.clip(1.0 - (dtheta / dir_penalty_scale) ** 2, 0.0, 1.0)
    score = np.where(gate_pass, score_base * fac, 0.0)

    out = cand.copy()
    out["cover_a"] = cover_a.astype("float64")
    out["mean_ptline_m"] = mean_ptline.astype("float64")
    out["dtheta_deg"] = dtheta.astype("float64")
    out["gate_pass"] = gate_pass
    out["score"] = score.astype("float64")
    return out


# --------------------------------------------------------------------------- #
# N2.d - Affectation hongroise par cluster local (unicite 1<->1)
# --------------------------------------------------------------------------- #
def hungarian_unique(pairs: pd.DataFrame) -> pd.DataFrame:
    """Resoudre l'unicite par cluster (composantes connexes du graphe biparti).

    Garantit qu'un meme troncon T1 (tgt) n'est affecte qu'a un seul troncon base
    T2 (src), et inversement, par ``linear_sum_assignment`` (cout = 1 - score)
    sur chaque cluster de concurrence.
    """
    if pairs.empty:
        return pd.DataFrame(columns=["src_idx", "tgt_idx", "score_assigned"])

    src_codes, _ = pd.factorize(pairs["src_idx"].to_numpy())
    tgt_codes, _ = pd.factorize(pairs["tgt_idx"].to_numpy())
    n_src = int(src_codes.max()) + 1
    n_tgt = int(tgt_codes.max()) + 1
    n_nodes = n_src + n_tgt

    rows = src_codes
    cols = tgt_codes + n_src
    adj = coo_matrix((np.ones(len(pairs)), (rows, cols)), shape=(n_nodes, n_nodes))
    adj = adj + adj.T
    _, labels = connected_components(adj, directed=False)
    pairs = pairs.assign(_comp=labels[src_codes])

    results: list[tuple[int, int, float]] = []
    for _, grp in pairs.groupby("_comp", sort=False):
        if grp["src_idx"].nunique() == 1:
            best = grp.loc[grp["score"].idxmax()]
            results.append((int(best["src_idx"]), int(best["tgt_idx"]), float(best["score"])))
            continue
        ls, ls_idx = pd.factorize(grp["src_idx"].to_numpy())
        lt, lt_idx = pd.factorize(grp["tgt_idx"].to_numpy())
        BIG = 10.0
        cost = np.full((ls_idx.size, lt_idx.size), BIG, dtype="float64")
        cost[ls, lt] = 1.0 - grp["score"].to_numpy()
        row_i, col_j = linear_sum_assignment(cost)
        for ri, cj in zip(row_i, col_j):
            if cost[ri, cj] >= BIG:
                continue
            results.append((int(ls_idx[ri]), int(lt_idx[cj]), float(1.0 - cost[ri, cj])))

    return pd.DataFrame(results, columns=["src_idx", "tgt_idx", "score_assigned"])


def _classify(
    score1: float,
    margin: float,
    *,
    score_auto: float = THR_AUTO,
    score_min: float = THR_REVIEW,
    margin_min: float = MARGIN_MIN,
) -> str:
    """Classer un appariement geometrique selon les seuils calibres.

    Les seuils sont injectes en parametres (defauts = constantes de module) :
    aucune lecture d'etat global mutable -> thread-safe.
    """
    if score1 < score_min:
        return "NON_MATCH"
    if score1 >= score_auto and margin >= margin_min:
        return "GEOM_AUTO"
    return "GEOM_VERIF"


def geometric_match(
    g_base: gpd.GeoDataFrame,
    g_t1: gpd.GeoDataFrame,
    residual_src: np.ndarray,
    *,
    score_auto: float = THR_AUTO,
    score_min: float = THR_REVIEW,
    margin: float = MARGIN_MIN,
    dtheta_reject: float = GATE_HARD_REJECT_DEG,
    dir_penalty_scale: float = DIR_PENALTY_SCALE_DEG,
) -> pd.DataFrame:
    """Appariement geometrique N2 des troncons base T2 residuels.

    Returns
    -------
    pandas.DataFrame
        Colonnes : src_idx, tgt_idx, match_score, match_level (GEOM_AUTO /
        GEOM_VERIF). Les NON_MATCH ne sont pas emis (le troncon reste residuel).
    """
    res_set = set(int(x) for x in residual_src.tolist())
    if not res_set:
        return pd.DataFrame(columns=["src_idx", "tgt_idx", "match_score", "match_level"])

    sub_base = g_base.loc[g_base.index.isin(res_set) & g_base["geom_ok"]]
    if sub_base.empty:
        return pd.DataFrame(columns=["src_idx", "tgt_idx", "match_score", "match_level"])

    cand = build_candidates(g_base, g_t1)
    cand = cand[cand["src_idx"].isin(res_set)]
    if cand.empty:
        return pd.DataFrame(columns=["src_idx", "tgt_idx", "match_score", "match_level"])
    # Cibles T1 valides uniquement.
    ok_t1 = set(g_t1.index[g_t1["geom_ok"]].tolist())
    cand = cand[cand["tgt_idx"].isin(ok_t1)]

    scored = score_pairs(
        g_base, g_t1, cand,
        dtheta_reject=dtheta_reject,
        dir_penalty_scale=dir_penalty_scale,
    )
    pairs = scored[scored["gate_pass"] & (scored["score"] > 0)][
        ["src_idx", "tgt_idx", "score"]
    ].copy()
    if pairs.empty:
        return pd.DataFrame(columns=["src_idx", "tgt_idx", "match_score", "match_level"])

    assigned = hungarian_unique(pairs)
    if assigned.empty:
        return pd.DataFrame(columns=["src_idx", "tgt_idx", "match_score", "match_level"])

    # Marge 1er-2e par src (sur tous les scores gate-OK).
    s_sorted = scored.sort_values(["src_idx", "score"], ascending=[True, False])
    grp = s_sorted.groupby("src_idx", sort=True)["score"]
    score2 = grp.apply(lambda x: x.iloc[1] if len(x) > 1 else 0.0).rename("score2")

    out = assigned.rename(columns={"score_assigned": "match_score"})
    out = out.merge(score2, left_on="src_idx", right_index=True, how="left")
    out["score2"] = out["score2"].fillna(0.0)
    out["margin"] = out["match_score"] - out["score2"]
    out["match_level"] = [
        _classify(s, m, score_auto=score_auto, score_min=score_min, margin_min=margin)
        for s, m in zip(out["match_score"].to_numpy(), out["margin"].to_numpy())
    ]
    out = out[out["match_level"] != "NON_MATCH"]
    return out[["src_idx", "tgt_idx", "match_score", "match_level"]].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# N3 - Verification BAN (filtre de securite uniquement)
# --------------------------------------------------------------------------- #
API_REVERSE = "https://api-adresse.data.gouv.fr/reverse/csv/"
BATCH_SIZE = 8000
MAX_RETRIES = 4
BACKOFF_BASE_S = 3.0
REQUEST_TIMEOUT_S = 300

# Colonnes candidates pour le NOM de voie (reference cote base T2). Sans l'une
# d'elles, aucune comparaison BAN n'est possible -> la validation est court-
# circuitee (pas d'appel reseau, concordance INDISPONIBLE).
STREET_NAME_COLS: tuple[str, ...] = ("ST_NAME", "nom", "name", "voie", "libelle", "lib_voie")


def detect_street_name_col(*gdfs: gpd.GeoDataFrame) -> str | None:
    """Detecter une colonne de nom de voie presente dans au moins une carte.

    La reference BAN n'est lue que cote base T2, mais on scrute toutes les cartes
    fournies par robustesse. Retourne le premier candidat de ``STREET_NAME_COLS``
    present quelque part, ou ``None`` si aucune carte n'expose de nom de voie.
    """
    present = [g for g in gdfs if g is not None]
    for col in STREET_NAME_COLS:
        if any(col in g.columns for g in present):
            return col
    return None


_VOIE_TOKENS = {
    "rue", "avenue", "av", "bd", "boulevard", "chemin", "ch", "impasse", "imp",
    "allee", "allees", "place", "pl", "route", "rte", "quai", "cours", "montee",
    "passage", "voie", "rond", "point", "giratoire", "carrefour", "pont", "la",
    "le", "les", "de", "du", "des", "d", "l", "saint", "st", "sainte", "ste",
    "grande", "petit", "petite", "vieux", "vieille",
}


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def is_road_code(s: object) -> bool:
    """Indiquer si un nom de voie est un CODE de route (D7, A7, RD383...)."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return False
    t = _strip_accents(str(s)).upper().strip().replace(" ", "")
    return bool(re.fullmatch(r"(R?[DNAM]|VC|RD|RN)\d+[A-Z]?", t))


def normalize_name(s: object) -> set[str]:
    """Normaliser un nom de voie en tokens significatifs (sans type de voie)."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return set()
    txt = _strip_accents(str(s)).lower()
    txt = "".join(ch if ch.isalnum() else " " for ch in txt)
    return {t for t in txt.split() if t and t not in _VOIE_TOKENS and len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    """Indice de Jaccard entre deux ensembles de tokens (NaN si vide)."""
    if not a or not b:
        return float("nan")
    union = len(a | b)
    return len(a & b) / union if union else float("nan")


def _ban_call(batch: pd.DataFrame, session=None) -> pd.DataFrame:
    """Appeler BAN reverse sur un lot de points (retries backoff exponentiel)."""
    import requests
    buf = _io.StringIO()
    batch[["src_idx", "lat", "lon"]].to_csv(buf, index=False)
    payload = buf.getvalue().encode("utf-8")
    last_exc: Exception | None = None
    poster = session or requests
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            files = {"data": ("in.csv", payload, "text/csv")}
            r = poster.post(API_REVERSE, files=files, timeout=REQUEST_TIMEOUT_S)
            r.raise_for_status()
            return pd.read_csv(_io.BytesIO(r.content), dtype={"src_idx": "int64"})
        except Exception as exc:  # noqa: BLE001 - on retente
            last_exc = exc
            time.sleep(BACKOFF_BASE_S * (2 ** (attempt - 1)))
    raise RuntimeError(f"BAN reverse echoue apres {MAX_RETRIES} tentatives: {last_exc}")


def validate_ban(
    g_base: gpd.GeoDataFrame,
    matches: pd.DataFrame,
    *,
    cache: dict[int, dict] | None = None,
    session=None,
    progress: Callable[[float, str], None] | None = None,
    name_col: str | None = None,
) -> pd.DataFrame:
    """Concordance BAN par reverse-geocoding des points milieux base T2.

    Filtre de SECURITE uniquement : ne sert qu'a retrograder un GEOM_AUTO en
    GEOM_VERIF sur MISMATCH. Reprise idempotente via ``cache`` (indexe src_idx,
    mute en place) : un point deja geocode n'est pas re-interroge.

    Parameters
    ----------
    g_base : geopandas.GeoDataFrame
        Base T2 en EPSG:2154 (avec geometrie, colonne ``HD`` ou nom de voie
        indisponible -> concordance INDETERMINE faute de reference).
    matches : pandas.DataFrame
        Appariements geometriques (src_idx -> match_level GEOM_*).
    cache : dict[int, dict], optional
        Cache reprise {src_idx: {ban_name, ban_type}}. Mute en place.
    name_col : str, optional
        Colonne de nom de voie de reference cote base T2. Si ``None`` (aucune
        reference detectee), la validation est COURT-CIRCUITEE : aucun appel
        reseau, toutes les concordances valent ``INDISPONIBLE``.

    Returns
    -------
    pandas.DataFrame
        src_idx, ban_concordance (MATCH / MISMATCH / INDISPONIBLE).
    """
    progress = progress or _noop_progress
    cache = cache if cache is not None else {}
    geom_only = matches[matches["match_level"].isin(["GEOM_AUTO", "GEOM_VERIF"])]
    src = geom_only["src_idx"].to_numpy().astype("int64")
    if src.size == 0:
        return pd.DataFrame(columns=["src_idx", "ban_concordance"])

    # Reference nom de voie cote base T2. Sans colonne de nom (ex. cartes Lyon),
    # toute concordance vaut INDISPONIBLE : inutile d'interroger le reseau BAN.
    # On court-circuite donc completement le reverse-geocoding (no-op reseau).
    has_ref = name_col is not None and name_col in g_base.columns
    if not has_ref:
        logger.warning(
            "Validation BAN court-circuitee : aucune colonne de nom de voie "
            "(%s) dans la base T2 -> %d troncon(s) GEOM_* marque(s) INDISPONIBLE "
            "(aucun appel reseau).",
            "/".join(STREET_NAME_COLS), src.size,
        )
        progress(1.0, "ban")
        return pd.DataFrame(
            {"src_idx": src, "ban_concordance": ["INDISPONIBLE"] * src.size}
        )

    geoms = g_base.geometry.values[src]
    mids = shapely.line_interpolate_point(geoms, 0.5, normalized=True)
    gs = gpd.GeoSeries(mids, crs=g_base.crs or CRS_L93).to_crs(CRS_WGS84)
    pts = pd.DataFrame({
        "src_idx": src,
        "lat": gs.y.to_numpy().round(6),
        "lon": gs.x.to_numpy().round(6),
    })

    todo = pts[~pts["src_idx"].isin(set(cache.keys()))].reset_index(drop=True)
    progress(0.0, "ban")
    if not todo.empty:
        n_batches = int(np.ceil(len(todo) / BATCH_SIZE))
        for j in range(n_batches):
            batch = todo.iloc[j * BATCH_SIZE:(j + 1) * BATCH_SIZE]
            try:
                resp = _ban_call(batch, session=session)
            except RuntimeError:
                # Reseau indisponible : on marque INDISPONIBLE (pas de cache).
                for sidx in batch["src_idx"].to_numpy():
                    cache.setdefault(int(sidx), {"ban_name": None, "ban_type": None})
                continue
            name_col = "result_name" if "result_name" in resp.columns else None
            street_col = "result_street" if "result_street" in resp.columns else None
            for _, row in resp.iterrows():
                nm = row.get(name_col) if name_col else None
                if (nm is None or pd.isna(nm)) and street_col:
                    nm = row.get(street_col)
                cache[int(row["src_idx"])] = {
                    "ban_name": nm,
                    "ban_type": row.get("result_type"),
                }
            progress((j + 1) / n_batches, "ban")

    rows: list[tuple[int, str]] = []
    ref_names = g_base[name_col].to_dict() if has_ref else {}
    for sidx in src:
        entry = cache.get(int(sidx))
        if not entry or entry.get("ban_name") is None:
            rows.append((int(sidx), "INDISPONIBLE"))
            continue
        ban_type = entry.get("ban_type")
        ref = ref_names.get(int(sidx)) if has_ref else None
        if not has_ref or ref is None or is_road_code(ref) \
                or ban_type not in ("housenumber", "street"):
            rows.append((int(sidx), "INDISPONIBLE"))
            continue
        jac = jaccard(normalize_name(ref), normalize_name(entry["ban_name"]))
        if np.isnan(jac):
            rows.append((int(sidx), "INDISPONIBLE"))
        else:
            rows.append((int(sidx), "MATCH" if jac >= 0.5 else "MISMATCH"))
    return pd.DataFrame(rows, columns=["src_idx", "ban_concordance"])


# --------------------------------------------------------------------------- #
# Interface publique
# --------------------------------------------------------------------------- #
def match_segments(
    gdf_t1: gpd.GeoDataFrame,
    gdf_t2: gpd.GeoDataFrame,
    *,
    use_ban: bool = True,
    score_auto: float = THR_AUTO,
    score_min: float = THR_REVIEW,
    margin: float = MARGIN_MIN,
    dtheta_reject: float = GATE_HARD_REJECT_DEG,
    progress: Callable[[float, str], None] | None = None,
    ban_cache: dict[int, dict] | None = None,
    ban_session=None,
) -> pd.DataFrame:
    """Apparier chaque troncon de la base T2 a son homologue T1 (3 niveaux).

    Parameters
    ----------
    gdf_t1, gdf_t2 : geopandas.GeoDataFrame
        Cartes normalisees (cf ``io.load_carte_geojson``). ``gdf_t2`` est la BASE.
    use_ban : bool
        Activer la verification N3 (reverse-geocoding BAN).
    score_auto, score_min, margin, dtheta_reject : float
        Seuils calibres (par defaut : 0.6366 / 0.565 / 0.05 / 120 deg).
    progress : callable(pct: float, stage: str), optional
        Reporter d'avancement.
    ban_cache : dict[int, dict], optional
        Cache BAN pour reprise idempotente (mute en place).

    Returns
    -------
    pandas.DataFrame
        Une ligne par troncon base T2 : ``id_t2`` (agregId base), ``id_t1``
        (agregId T1 apparie ou ``None``), ``match_level`` (CLE / GEOM_AUTO /
        GEOM_VERIF / NON_MATCH), ``match_score`` (float pour GEOM_*, ``None``
        sinon), ``ban_concordance`` (MATCH / MISMATCH / INDISPONIBLE).
    """
    progress = progress or _noop_progress
    # Seuils runtime injectes dans les helpers (params/closure) : AUCUNE mutation
    # de global de module -> deux generations concurrentes (asyncio.to_thread)
    # avec des seuils differents n'interferent pas.

    progress(0.02, "prepare")
    g_base = _prepare_l93(gdf_t2)
    g_t1 = _prepare_l93(gdf_t1)

    base_ids = g_base["agregId"].astype("object").to_numpy()
    n_base = len(g_base)

    # --- N1 - CLE EXACTE ------------------------------------------------- #
    progress(0.15, "cle")
    t1_ids = g_t1["agregId"].astype("object")
    # Premier index T1 par agregId (unicite : un T1 ne sert qu'une cle).
    t1_id_to_idx: dict[str, int] = {}
    for i, val in enumerate(t1_ids.to_numpy()):
        if val is not None and val not in t1_id_to_idx:
            t1_id_to_idx[val] = i

    id_t1: list[str | None] = [None] * n_base
    match_level = np.array(["NON_MATCH"] * n_base, dtype=object)
    match_score: list[float | None] = [None] * n_base
    used_t1: set[int] = set()

    for i in range(n_base):
        bid = base_ids[i]
        if bid is not None and bid in t1_id_to_idx:
            tj = t1_id_to_idx[bid]
            id_t1[i] = bid
            match_level[i] = "CLE"
            used_t1.add(tj)

    # --- N2 - GEOMETRIQUE sur le residuel -------------------------------- #
    progress(0.30, "geo")
    residual_src = np.array([i for i in range(n_base) if match_level[i] == "NON_MATCH"], dtype="int64")
    # T1 deja consommes par la cle sont exclus des candidats geo (unicite).
    g_t1_free = g_t1.copy()
    if used_t1:
        g_t1_free.loc[list(used_t1), "geom_ok"] = False

    geo = geometric_match(
        g_base, g_t1_free, residual_src,
        score_auto=score_auto,
        score_min=score_min,
        margin=margin,
        dtheta_reject=dtheta_reject,
        dir_penalty_scale=dtheta_reject,
    )
    for _, r in geo.iterrows():
        i = int(r["src_idx"])
        id_t1[i] = g_t1.at[int(r["tgt_idx"]), "agregId"]
        match_level[i] = r["match_level"]
        match_score[i] = float(r["match_score"])

    ban_concordance = np.array([None] * n_base, dtype=object)

    matches = pd.DataFrame({
        "src_idx": np.arange(n_base),
        "match_level": match_level,
    })

    # --- N3 - BAN (filtre securite) -------------------------------------- #
    if use_ban:
        progress(0.70, "ban")
        # Auto-detection d'une colonne de nom de voie commune aux deux cartes.
        # Absente (ex. cartes Lyon) -> validate_ban court-circuite le reseau et
        # marque INDISPONIBLE (cf detect_street_name_col / validate_ban).
        name_col = detect_street_name_col(gdf_t2, gdf_t1)
        if name_col is None:
            logger.warning(
                "use_ban=True mais aucune colonne de nom de voie (%s) commune "
                "aux deux cartes -> BAN no-op reseau (concordance INDISPONIBLE).",
                "/".join(STREET_NAME_COLS),
            )
        ban_df = validate_ban(
            g_base, matches, cache=ban_cache, session=ban_session,
            progress=progress, name_col=name_col,
        )
        ban_map = dict(zip(ban_df["src_idx"].to_numpy(), ban_df["ban_concordance"].to_numpy()))
        for i in range(n_base):
            if match_level[i] in ("GEOM_AUTO", "GEOM_VERIF"):
                conc = ban_map.get(i, "INDISPONIBLE")
                ban_concordance[i] = conc
                if conc == "MISMATCH" and match_level[i] == "GEOM_AUTO":
                    match_level[i] = "GEOM_VERIF"  # retrogradation, jamais promotion

    progress(1.0, "done")
    # match_score / ban_concordance en dtype object pour PRESERVER None (le
    # contrat impose None — pas NaN — pour CLE/NON_MATCH et BAN non evalue).
    score_arr = np.empty(n_base, dtype=object)
    for i in range(n_base):
        score_arr[i] = match_score[i]
    id_t1_arr = np.empty(n_base, dtype=object)
    for i in range(n_base):
        id_t1_arr[i] = id_t1[i]
    return pd.DataFrame({
        "id_t2": np.asarray(base_ids, dtype=object),
        "id_t1": id_t1_arr,
        "match_level": np.asarray(match_level, dtype=object),
        "match_score": score_arr,
        "ban_concordance": ban_concordance,
    })
