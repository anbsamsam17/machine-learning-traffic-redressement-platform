# 00 — Méthodologie consolidée : détection de discontinuités TVr

**Statut.** Document maître. Auto-suffisant : un développeur peut implémenter à partir
de ce seul fichier. Références aux notes amont entre parenthèses (`01:§x` /  `02:§y`).

---

## Section 1 — Executive summary

### Problem statement

Le fichier `2025.geojson` (241 857 brins directionnels HERE, 29 colonnes, EPSG:4326)
expose pour chaque brin une prédiction TVr (véhicules/jour). Sur un réseau aussi grand,
des incohérences locales du modèle se manifestent (a) entre deux brins consécutifs d'un
même couloir (relay) et (b) au niveau des carrefours physiques (Σ entrée ≠ Σ sortie).
Objectif : produire une **liste classée de discontinuités** prêt-à-réviser en QGIS, avec
sévérité, justification, et géométrie alignée sur le sens de circulation.

### Méthodologie 2-phases

```
PHASE 1 — Couche graphe (01_graph_reconstruction.md)
  Entrée GeoJSON brut → arêtes dirigées (in_node, out_node) → adjacence (out_links, in_links)
  → catégorisation (oneway / bidir / ramp / roundabout) → tags boundaries.

PHASE 2 — Couche analytique (02_continuity_and_conservation.md)
  A. Continuité inter-brins (paires u→v, écarts TVr par tier de flux)
  B. Conservation aux nœuds (Σin vs Σout par jonction, GEH + déséquilibre relatif)
  C. Score composite par arête, anti-double-count entre A et B.
```

### Outputs et usages

| Output | Format | Usage |
|---|---|---|
| `discontinuity_edges.geojson` | EPSG:4326 GeoJSON | revue cartographique QGIS, top-N par sévérité |
| `discontinuity_nodes.csv` | UTF-8 CSV | inspection tabulaire des nœuds problématiques |
| `discontinuity_nodes_all.csv` | UTF-8 CSV | diagnostic exhaustif (non filtré) |
| `discontinuity_qc.json` | JSON | comptages, percentiles, seuils utilisés (audit trail) |

---

## Section 2 — Pipeline diagram

```
 ┌──────────────────────────────┐
 │  2025.geojson (241 857 rows) │   29 cols, HERE schema
 └────────────┬─────────────────┘
              ▼
 ┌──────────────────────────────┐
 │ S1. Load + validate          │   drop self-loops, dup agregId; QC report
 └────────────┬─────────────────┘
              ▼
 ┌──────────────────────────────┐
 │ S2. Build directed edges     │   expand -F/-T → in_node, out_node, geom_aligned
 └────────────┬─────────────────┘
              ▼
 ┌──────────────────────────────┐
 │ S3. Adjacency + category     │   out_links, in_links, edge_category, boundaries
 └────────────┬─────────────────┘
              ▼
 ┌──────────────────────────────┐
 │ S4. Inter-segment continuity │   paires u→v, deltas TVr, GEH, flag flow-tiered
 └────────────┬─────────────────┘
              ▼
 ┌──────────────────────────────┐
 │ S5. Node conservation        │   Σin/Σout par jonction, GEH_node, rel_imbalance
 └────────────┬─────────────────┘
              ▼
 ┌──────────────────────────────┐
 │ S6. Composite severity       │   anti-double-count, top_issue, ranking
 └────────────┬─────────────────┘
              ▼
 ┌──────────────────────────────┐
 │ S7. Export (CSV + GeoJSON)   │   edges + nodes + QC
 └──────────────────────────────┘
```

---

## Section 3 — Stage-by-stage methodology

### Stage 1 — Load + sanity check

- **What.** Lire le GeoJSON, valider le schéma, supprimer les lignes inutilisables.
- **Inputs.** `2025.geojson` (29 colonnes). Clés : `agregId:str`, `REF_IN_ID:int`,
  `NREF_IN_ID:int`, `DD:bool`, `TVr:int`, `FC:int`, `RAMP:str`, `ROUNDABOUT:str`,
  `geometry:LINESTRING`.
- **Algorithm.**
  ```python
  gdf = gpd.read_file(src)   # EPSG:4326
  qc = {"n_rows_in": len(gdf)}
  # drop missing endpoints
  bad = gdf["REF_IN_ID"].isna() | gdf["NREF_IN_ID"].isna()
  qc["dropped_missing_endpoints"] = int(bad.sum()); gdf = gdf.loc[~bad]
  # drop self-loops (none expected on 2025)
  sl = gdf["REF_IN_ID"] == gdf["NREF_IN_ID"]
  qc["dropped_self_loops"] = int(sl.sum()); gdf = gdf.loc[~sl]
  # duplicate agregId is fatal
  dup = gdf["agregId"].duplicated(keep="first")
  if dup.any():
      raise ValueError(f"duplicate agregId: {gdf.loc[dup,'agregId'].head().tolist()}")
  ```
- **Outputs.** `gdf` nettoyé + `qc` dict.
- **Edge cases.** `agregId` dupliqué = fatal (raise). Endpoints manquants = drop+log.
  Self-loops = drop (jamais observés sur Lyon 2025).
- **Justification.** Voir `01:§4` (table sanity checks).

### Stage 2 — Build directed edges

- **What.** Déduire `in_node`/`out_node` du suffixe `-F`/`-T`, aligner la géométrie sur
  le sens de circulation.
- **Inputs.** colonnes `agregId`, `DD`, `REF_IN_ID`, `NREF_IN_ID`, `geometry`.
- **Algorithm.**
  ```python
  gdf["base_id"] = gdf["agregId"].apply(
      lambda a: a.rsplit("-",1)[0] if a.endswith(("-F","-T")) else a)
  suffix = gdf["agregId"].str.extract(r"-([FT])$", expand=False)
  gdf["dir_class"] = pd.Categorical(
      suffix.where(gdf["DD"], "O").fillna("F"),
      categories=["F","T","O"])
  is_T = gdf["dir_class"].eq("T")
  gdf["in_node"]  = gdf["NREF_IN_ID"].where(is_T, gdf["REF_IN_ID"]).astype("int64")
  gdf["out_node"] = gdf["REF_IN_ID"].where(is_T, gdf["NREF_IN_ID"]).astype("int64")
  gdf["geom_aligned"] = [
      LineString(list(g.coords)[::-1]) if t else g
      for g, t in zip(gdf.geometry, is_T)]
  ```
- **Outputs.** colonnes ajoutées : `base_id:str`, `dir_class:cat{F,T,O}`,
  `in_node:int64`, `out_node:int64`, `geom_aligned:LineString`.
- **Edge cases.** `DD=True` sans suffixe (anomalie) → forcer `dir_class=F` + warn.
  `DD=False` avec suffixe → suivre le suffixe + warn. Géométrie toujours `REF→NREF`
  dans la source ; pour `dir_class=T` on inverse les coordonnées (`01:§1.2`).
- **Justification.** TVr est direction-spécifique (85 % des paires -F/-T ont des
  valeurs différentes) ; collapser en arête non-dirigée masquerait le signal et casserait
  la conservation aux nœuds bidirectionnels (`01:§1.1`).

### Stage 3 — Adjacency + category + boundaries

- **What.** Construire `out_links`/`in_links`, catégoriser chaque arête, tagger les
  frontières du réseau.
- **Inputs.** `in_node`, `out_node`, `base_id`, `RAMP`, `ROUNDABOUT`, `dir_class`.
- **Algorithm.**
  ```python
  out_by_node = edges.groupby("in_node")["agregId"].agg(list)
  in_by_node  = edges.groupby("out_node")["agregId"].agg(list)
  edges["out_links_raw"] = edges["out_node"].map(out_by_node).apply(_as_list)
  edges["in_links_raw"]  = edges["in_node"].map(in_by_node).apply(_as_list)
  # supprimer le frère U-turn (un -F ne liste pas son -T comme voisin aval)
  base_of = dict(zip(edges["agregId"], edges["base_id"]))
  edges["out_links"] = [[x for x in lst if base_of.get(x)!=b]
                       for lst,b in zip(edges["out_links_raw"], edges["base_id"])]
  edges["in_links"]  = [[x for x in lst if base_of.get(x)!=b]
                       for lst,b in zip(edges["in_links_raw"], edges["base_id"])]
  edges["out_deg"] = edges["out_links"].str.len()
  edges["in_deg"]  = edges["in_links"].str.len()
  edges["edge_category"] = edges.apply(categorise, axis=1).astype("category")
  edges["is_isolated"] = (edges["in_deg"]==0) & (edges["out_deg"]==0)
  edges["is_source"]   = edges["in_deg"]==0
  edges["is_sink"]     = edges["out_deg"]==0
  ```
  où `categorise(row)` retourne `"roundabout"` si `ROUNDABOUT=='Y'`, sinon `"ramp"` si
  `RAMP=='Y'`, sinon `"oneway"` si `dir_class=='O'`, sinon `"bidir"`.
- **Outputs.** `out_links:list[str]`, `in_links:list[str]`, `out_deg:int16`,
  `in_deg:int16`, `edge_category:cat`, `is_source:bool`, `is_sink:bool`,
  `is_isolated:bool`.
- **Edge cases.** Ramps : arêtes normales, juste taguées (`01:§2.2`). Roundabouts :
  l'adjacence native HERE câble correctement l'anneau, pas de logique custom
  (`01:§2.3`). Multi-leg ≥ 3 : aucune action particulière (`01:§2.4`).
- **Justification.** DSU non requis : les `REF_IN_ID`/`NREF_IN_ID` HERE encodent déjà
  la jonction physique (`01:§3`).

### Stage 4 — Inter-segment continuity (Check A)

- **What.** Pour chaque paire `u→v` avec `v ∈ u.out_links`, calculer Δ TVr et flagger
  selon une grille tiered par flux.
- **Inputs.** colonnes `TVr`, `out_links`, `out_deg`, `in_deg`, `edge_category`,
  `is_source`, `is_sink`, `FC`.
- **Algorithm (vectorisé, ~390 k paires en < 2 s).**
  ```python
  pairs = (edges.explode("out_links")
                .rename(columns={"out_links":"v_id"})
                .merge(edges[["agregId","TVr","FC","in_deg","edge_category"]]
                       .rename(columns={"agregId":"v_id","TVr":"TVr_v",
                                        "FC":"FC_v","in_deg":"in_deg_v",
                                        "edge_category":"ec_v"}),
                       on="v_id", how="inner"))
  # filtres skip
  skip = (pairs["is_sink"] | pairs["TVr"].isna() | (pairs["TVr"]<0)
          | pairs["TVr_v"].isna() | (pairs["TVr_v"]<0)
          | (pairs["out_deg"]>=2) | (pairs["in_deg_v"]>=2)
          | ((pairs["edge_category"]=="roundabout") & (pairs["ec_v"]=="roundabout")))
  pairs = pairs.loc[~skip]
  # métriques
  pairs["max_flow"] = np.maximum(pairs["TVr"], pairs["TVr_v"])
  pairs["delta_abs"] = pairs["TVr_v"] - pairs["TVr"]
  pairs["delta_rel"] = pairs["delta_abs"].abs() / pairs["max_flow"].clip(lower=1)
  pairs["GEH_pair"]  = compute_geh(pairs["TVr"], pairs["TVr_v"])
  # tier-based cuts via np.select  (voir grille ci-dessous)
  pairs["flag"] = (pairs["delta_rel"]>rel_cut) & (pairs["delta_abs"].abs()>abs_cut) \
                & (pairs["GEH_pair"]>geh_cut)
  pairs["severity_pair"] = pairs["GEH_pair"] * np.sqrt(pairs["max_flow"])
  ```
- **Grille flow-tiered (`02:§A.3`).**

  | max(TVr_u, TVr_v) | Δrel | Δabs (veh/j) | GEH_pair |
  |---|---|---|---|
  | < 500 | 50 % | 200 | 10 |
  | 500–2 000 | 30 % | 400 | 14 |
  | 2 000–5 000 | 22 % | 700 | 17 |
  | 5 000–10 000 | 22 % | 1 200 | 20 |
  | > 10 000 | 18 % | 1 800 | 22 |

  Modulateurs : `edge_category=="ramp"` → `rel_cut ×1.5` ; `|FC_u-FC_v|≥2` →
  `rel_cut ×1.3`.
- **Outputs.** Table `pairs` avec `flag:bool`, `severity_pair:float`, `GEH_pair`,
  `delta_rel`, `delta_abs`.
- **Edge cases.** Divergence (`out_deg≥2`) ou convergence (`in_deg_v≥2`) → skip
  (variation légitime, traitée par S5). Roundabouts internes → skip. Sources/sinks →
  skip (effet de bord). NaN/négatif → log uniquement.
- **Justification.** AND-of-three pour éviter les faux positifs sur les petites
  rues bruitées. Grille ancrée sur la tolérance dynamique validée en production
  (`evaluation_pipeline.py:291-300` ; ±14/18/25 % selon le tier).

### Stage 5 — Node-level conservation (Check B)

- **What.** Pour chaque jonction physique (`node_id`), comparer Σ TVr entrant et
  Σ TVr sortant.
- **Inputs.** `in_node`, `out_node`, `TVr`.
- **Algorithm.**
  ```python
  in_flow  = edges.groupby("out_node")["TVr"].sum().rename("in_flow")
  out_flow = edges.groupby("in_node")["TVr"].sum().rename("out_flow")
  nodes = pd.concat([in_flow, out_flow], axis=1).fillna(0.0).reset_index()
  nodes = nodes.rename(columns={"index":"node_id"})
  nodes["max_flow"]      = nodes[["in_flow","out_flow"]].max(axis=1)
  nodes["abs_imbalance"] = (nodes["in_flow"]-nodes["out_flow"]).abs()
  nodes["rel_imbalance"] = nodes["abs_imbalance"] / nodes["max_flow"].clip(lower=1)
  nodes["GEH_node"]      = compute_geh(nodes["in_flow"], nodes["out_flow"])
  nodes["is_boundary"]   = (nodes["in_flow"]==0) | (nodes["out_flow"]==0)
  nodes["n_in_edges"]    = edges.groupby("out_node").size().reindex(nodes.node_id, fill_value=0).values
  nodes["n_out_edges"]   = edges.groupby("in_node").size().reindex(nodes.node_id, fill_value=0).values
  nodes["is_bad"] = (
      ~nodes["is_boundary"]
      & (nodes["max_flow"] >= 3000)
      & ((nodes["GEH_node"] > 15) | (nodes["rel_imbalance"] > 0.18)))
  nodes["severity_node"] = nodes["GEH_node"] * np.sqrt(nodes["max_flow"])
  ```
- **Outputs.** Table `nodes` (~120 k lignes Lyon-scale).
- **Edge cases.** Nœuds frontière (in_flow=0 OR out_flow=0) → tag seulement, jamais
  flagger. min_flow=3000 véh/j pour éviter le bruit local.
- **Justification.** Seuils ancrés sur `discontinuity.py:99-106` + tolérance ±18 %
  du tier 2 k–10 k. OR (et non AND) entre GEH et rel_imbalance car ils captent des
  régimes différents (gros nœud absolu vs nœud moyen déséquilibré) (`02:§B.3`).

### Stage 6 — Composite severity per edge + ranking

- **What.** Agréger pour chaque arête les flags A et B en un score composite, avec
  règle anti-double-count.
- **Inputs.** Sortie de S4 (`pairs`) et S5 (`nodes`), joints sur `agregId` via
  `in_node`/`out_node`.
- **Algorithm.**
  ```python
  # severities par nœud incident
  edges = edges.merge(nodes[["node_id","is_bad","severity_node"]]
                          .rename(columns={"node_id":"in_node",
                                           "is_bad":"in_bad",
                                           "severity_node":"sev_in"}),
                      on="in_node", how="left")
  edges = edges.merge(nodes[["node_id","is_bad","severity_node"]]
                          .rename(columns={"node_id":"out_node",
                                           "is_bad":"out_bad",
                                           "severity_node":"sev_out"}),
                      on="out_node", how="left")
  # severities par paire (worst-incoming, worst-outgoing)
  worst_out = pairs.loc[pairs.flag].groupby("agregId")["severity_pair"].max()
  worst_in  = pairs.loc[pairs.flag].groupby("v_id")["severity_pair"].max()
  edges["sev_pair_down"] = edges["agregId"].map(worst_out).fillna(0.0)
  edges["sev_pair_up"]   = edges["agregId"].map(worst_in).fillna(0.0)
  # anti-double-count : si un endpoint est bad-node, on n'ajoute pas la paire
  pair_mask = ~(edges["in_bad"].fillna(False) | edges["out_bad"].fillna(False))
  score_pair = pair_mask * np.maximum(edges["sev_pair_up"], edges["sev_pair_down"])
  score_node = np.maximum(edges["sev_in"].fillna(0), edges["sev_out"].fillna(0))
  edges["composite_severity"] = 0.6*score_node + 0.4*score_pair
  edges["top_issue"] = _argmax_top_issue(edges)   # voir C.2
  ```
- **Outputs.** Colonnes ajoutées : `composite_severity:float`, `top_issue:enum`,
  `jump_upstream_pp`, `jump_downstream_pp`, `node_imbalance_in`,
  `node_imbalance_out`, `GEH_node_in`, `GEH_node_out`.
- **Edge cases.** Si arête sans flag (aucun voisin / sinks / boundaries) →
  `composite_severity = 0`, pas exportée dans le GeoJSON final (mais conservée
  pour les joins en amont).
- **Justification.** Poids 0.6 (nœud) / 0.4 (paire) : un déséquilibre de nœud
  implique un mismatch structurel global, alors qu'une paire isolée est locale
  (`02:§C.2`).

### Stage 7 — Export

- **What.** Sérialiser les 4 livrables.
- **Outputs.**
  - `discontinuity_edges.geojson` (EPSG:4326) : arêtes avec
    `composite_severity > 0`, triées descendant, géométrie `geom_aligned`.
  - `discontinuity_nodes.csv` : nœuds avec `is_bad=True`.
  - `discontinuity_nodes_all.csv` : tous les nœuds (diagnostic).
  - `discontinuity_qc.json` : compteurs + thresholds utilisés + percentiles
    (p50/p95 de `GEH_pair`, `rel_imbalance`, `composite_severity`).

---

## Section 4 — Output schema reference

### `discontinuity_nodes.csv`

| col | type | description |
|---|---|---|
| `node_id` | int64 | identifiant HERE de la jonction physique |
| `in_flow` | float | Σ TVr des arêtes entrantes (`out_node==node_id`) |
| `out_flow` | float | Σ TVr des arêtes sortantes (`in_node==node_id`) |
| `abs_imbalance` | float | `|in_flow - out_flow|` |
| `rel_imbalance` | float | `abs_imbalance / max(in_flow, out_flow)` |
| `GEH_node` | float | `sqrt(2*(in-out)^2 / (in+out))` |
| `n_in_edges` | int | nombre d'arêtes entrantes |
| `n_out_edges` | int | nombre d'arêtes sortantes |
| `is_boundary` | bool | `in_flow==0 OR out_flow==0` |
| `is_bad` | bool | flag final selon règle B.3 |
| `severity_node` | float | `GEH_node * sqrt(max_flow)` |
| `rank` | int | rang descendant sur `severity_node` |

### `discontinuity_edges.geojson` (propriétés)

| prop | type | description |
|---|---|---|
| `agregId` | str | PK directionnelle |
| `REF_IN_ID`, `NREF_IN_ID` | int64 | endpoints HERE bruts |
| `in_node`, `out_node` | int64 | endpoints orientés sens-de-circulation |
| `TVr` | float | flux prédit (véh/j) |
| `FC` | int8 | functional class |
| `edge_category` | str | `oneway` / `bidir` / `ramp` / `roundabout` |
| `jump_upstream_pp` | float | GEH max sur paire entrante flaggée (NaN si aucune) |
| `jump_downstream_pp` | float | GEH max sur paire sortante flaggée |
| `node_imbalance_in` | float | rel_imbalance à `in_node` (NaN si boundary) |
| `node_imbalance_out` | float | rel_imbalance à `out_node` |
| `GEH_node_in` | float | GEH à `in_node` |
| `GEH_node_out` | float | GEH à `out_node` |
| `composite_severity` | float | `0.6*score_node + 0.4*score_pair` |
| `top_issue` | enum | `jump_up` / `jump_down` / `node_in_imbalance` / `node_out_imbalance` |
| `geometry` | LineString | issue de `geom_aligned` (sens circulation) |

---

## Section 5 — Numerical examples

### Exemple 1 — Carrefour en T (3 arêtes)

Jonction `j=4242` : 2 arêtes entrantes `e1` (TVr=8 000) et `e2` (TVr=2 000),
1 arête sortante `e3` (TVr=11 500).

**Check A (inter-segment).** `e1.out_deg=1`, `e3.in_deg=2` → la paire `e1→e3` est
**skipped** (`in_deg_v≥2`). Pareil pour `e2→e3`. **Aucun flag A** : c'est la règle —
une convergence n'a pas de comparaison pair-wise pertinente.

**Check B (node).**
```
in_flow  = 8000 + 2000 = 10 000
out_flow = 11 500
max_flow = 11 500
abs_imb  = 1 500
rel_imb  = 1500 / 11500 = 0.130   (13.0 %)
GEH_node = sqrt(2*1500^2 / 21500) = sqrt(209.3) = 14.47
```
Tests : `max_flow ≥ 3 000` OK ; `GEH=14.47 > 15` NON ; `rel_imb=13% > 18%` NON →
**non flaggé**. Le déséquilibre de 1 500 véh/j n'est pas suffisant pour cette
ampleur de flux.

Si en revanche `e3.TVr` était 14 500 (au lieu de 11 500) :
```
abs_imb=4 500, rel_imb=0.310, GEH = sqrt(2*4500^2 / 24500) = 28.7
```
`GEH > 15` OR `rel_imb > 0.18` → **flaggé**. `severity_node = 28.7*sqrt(14500) = 3 455`.

### Exemple 2 — Relay 1-in 1-out, saut 1200 → 1800

Brins `e1` (TVr=1 200, out_deg=1) → `e2` (TVr=1 800, in_deg=1), même FC, pas ramp.

```
max_flow  = 1 800
delta_abs = 600
delta_rel = 600 / 1800 = 0.333  (33.3 %)
GEH_pair  = sqrt(2*600^2 / 3000) = sqrt(240) = 15.49
```

Tier = `500–2 000` → cuts `(30 %, 400, 14)`.
- `33.3 % > 30 %` OK
- `600 > 400` OK
- `15.49 > 14` OK
- → **flaggé**. `severity_pair = 15.49 * sqrt(1800) = 657`.

Vérification anti-double-count : si la jonction sortante de `e2` est elle-même
flaggée comme bad node, alors la paire n'est PAS comptée dans `composite_severity`
(voir S6). Sinon, `composite_severity = 0.4 * 657 = 263`, `top_issue="jump_up"`
sur `e2` (ou `"jump_down"` sur `e1` selon orientation).

---

## Section 6 — Implementation checklist

### Dependencies

```
python>=3.11
geopandas>=0.14
pandas>=2.0
numpy>=1.24
shapely>=2.0
networkx>=3.0       # optionnel : utile pour debug, pas requis pour le pipeline
pyogrio>=0.7        # accélérateur read_file
```

### Estimated runtime (laptop i7, 16 GB RAM, 241 857 edges)

| stage | temps |
|---|---|
| S1 read_file (pyogrio) | ~15 s |
| S2 directed edges | < 1 s |
| S3 adjacency + category | ~3 s |
| S4 pair check (vectorisé) | < 2 s |
| S5 node check (2 groupbys) | < 1 s |
| S6 composite + ranking | ~2 s |
| S7 export | ~3 s |
| **Total** | **~25 s end-to-end** |

### Suggested unit tests

1. **base_id parsing** : `"1000-F"→"1000"`, `"1000-T"→"1000"`, `"1000"→"1000"`.
2. **dir_class assignment** : DD=True+`-F` → `F`+`in_node=REF` ; DD=True+`-T` →
   `T`+`in_node=NREF` ; DD=False sans suffixe → `O`.
3. **geom_aligned reversal** : pour `-T`, premier point = NREF, dernier = REF.
4. **U-turn sibling suppression** : edge `X-F` arrivant au nœud N ne liste PAS
   `X-T` dans `out_links` même si `X-T` part de N.
5. **Adjacency symmetry** : si `v ∈ u.out_links` alors `u ∈ v.in_links`.
6. **Pair skip at divergence** : 1 edge avec out_deg=2 → aucune paire en sortie
   dans `pairs` après filtres.
7. **GEH formula** : `compute_geh(100,100)=0`, `compute_geh(100,0)=14.14`.
8. **Node conservation balanced** : carrefour 4 arêtes (2 in à 1000, 2 out à 1000)
   → `is_bad=False`, `rel_imbalance=0`.
9. **Tier classification** : un Δrel=20%, Δabs=300, max_flow=1800 doit déclencher
   le tier `500–2000` (cuts 30/400/14) et NE PAS flagger (delta_abs<400).
10. **Anti-double-count** : edge avec node bad ET pair bad → seul le node compte
    dans le composite ; pair n'inflate pas la sévérité.

### Performance tips

- **Vectoriser S4** via `explode` + `merge` (`02:§A.6`), ne JAMAIS boucler sur
  les arêtes Python-side.
- **`pd.Categorical`** sur `dir_class` et `edge_category` (économise ~30 MB
  RAM sur 241 k lignes).
- **`pyogrio`** pour `read_file` (3-4× plus rapide que `fiona`).
- **`np.select`** pour la grille tiered, pas une apply ligne-à-ligne.
- **Index sur `node_id`** dans la table nodes avant les merges S6.
- **Drop `out_links_raw`/`in_links_raw`** après filtrage U-turn (économise
  ~50 MB sur 241 k arêtes).

---

## Section 7 — Open questions for human review

### Décisions BLOQUANTES (input humain requis avant implémentation)

1. **`DD=True` orphelins (`-F` sans `-T` ou inverse).** Garder tel quel comme
   one-way (proposition par défaut), ou synthétiser le sibling manquant avec
   `TVr=NaN` ? Impact : nombre exact d'arêtes finales (cf. `01:§7.1`).

### Décisions DIFFÉRABLES (defaults valables, à re-tuner après QGIS review)

2. **Pondération composite 0.6 / 0.4** (node vs pair). Défendable mais arbitraire ;
   re-tuner sur jeu labellisé (`02:§E.1`).
3. **Roundabouts : skip total des paires internes.** Certaines discontinuités
   internes peuvent être réelles ; envisager une grille ×2 plus lâche dans un
   second pass (`02:§E.2`).
4. **Nœuds frontière silencieux.** Pourraient signaler un brin manquant dans la
   source ; check « coverage » séparé recommandé plutôt que mix avec
   conservation (`02:§E.3`).
5. **TVr=0 + DPL<0 sur one-way.** Confirmer que c'est un résidu modèle, pas une
   erreur data ; laisser intact (cf. `01:§7.2`).
6. **Suppression cross-FC ≥3.** Étendre le filtre U-turn aux voisins dont
   `|FUNC_CLASS_u - FUNC_CLASS_v| ≥ 3` (brins piétons Class 5 sur trunk Class 2) ?
   Actuellement géré en aval par `deadend_last_brins` (`01:§7.3`).
7. **GEH threshold daily-scaled à 15.** Choix mid-range entre OK (12) et flag
   (20) ; pourrait être ajusté à 12 ou 18 selon le bruit observé sur Lyon
   (`02:§0`).
