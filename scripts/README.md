# Scripts d'analyse et de preparation des donnees

Ce dossier regroupe les pipelines hors-application (data engineering) utilises
pour preparer et analyser les jeux de donnees Lyon / Grand Lyon. Ces scripts ne
font pas partie de l'application web : ils sont lances ponctuellement en local
pour produire des livrables (parquet, GeoJSON, cartes HTML) qui sont ensuite
consommes par l'API ou par les modules de visualisation.

## Variable d'environnement commune : `MDL_DATA_ROOT`

Tous les scripts ci-dessous lisent leurs donnees sources depuis une racine
externe configurable :

```bash
export MDL_DATA_ROOT=/chemin/vers/mdl-data
```

Par defaut (variable absente), la racine vaut `~/mdl-data`
(`Path.home() / "mdl-data"`). Les chemins sources sont construits relativement
a cette racine (sous-dossiers `Travaux_donnees_Lyon/`, `Travaux_Python/`, etc.).

---

## 1. `enrich_fcdrefglobal.py` — Enrichissement FCDREFGLOBAL 2025

**But** : produire le fichier `FCDREFGLOBAL_2025` pret a l'emploi pour les
modeles `MDL_Lyon_TV_Final` et `MDL_Lyon_PL_Final` (renommage au schema de
training + features derivees).

**Entree -> sortie**
- Entree : `FCDREFGLOBAL_2025_GrandLyon_imputed.parquet` (**241 857 segments**),
  sous `Travaux_donnees_Lyon/Livrables/FCDREFGLOBAL/`.
- Sortie : `FCDREFGLOBAL_2025.parquet` dans le meme dossier
  (l'export `.geojson` est desactive par defaut — ~1,4 GB).

**Traitements**
- 3 renommages simples (`TMJFCDTV->TMJOFCDTV`, `TMJFCDPL->TMJOFCDPL`,
  `FUNC_CLASS->functional_class`).
- 6 renommages avec conversion **km -> m** (distances VL/PL) pour coller aux
  colonnes suffixees `_m` du training.
- 4 colonnes ajoutees : `Annee` (= 2025), `fcd_log` (= ln(1 + TMJOFCDPL)),
  `tv_pl_ratio` (= TMJOFCDTV / (TMJOFCDPL + 0.1)),
  `dist_to_lyon_center` (Haversine en km du centroide du LINESTRING vers la
  Place Bellecour, 45.7578 N / 4.8320 E).

**Format** : Parquet (geometrie + schema complet preserves), CRS EPSG:4326.

**Lancement**
```bash
python scripts/enrich_fcdrefglobal.py
```

---

## 2. `map_2025_light/` — Carte MapLibre autonome (reseau 2025)

**But** : optimiser le reseau `2025_light.geojson` pour une carte MapLibre
autonome (allegement des proprietes, arrondi des coordonnees) et generer une
page HTML standalone avec capteurs TV/PL superposables.

**Entree -> sortie**
- Entree principale : `2025_light.geojson`
  (**~81 MB, 98 129 LineStrings, 31 proprietes/feature**), sous
  `Travaux_donnees_Lyon/Livrables/`.
- Sources capteurs (build_v2) : `BCFCDREF_AllYears_TV.parquet` et
  `BCFCDREF_AllYears_PL_enriched.geojson`, sous
  `Travaux_donnees_Lyon/DataApprentissage/`.
- Sorties : `2025_light.min.geojson` (+ jumeau `.gz`),
  `sensors_tv.min.geojson`, `sensors_pl.min.geojson`, `index.html`.

**Traitements**
- `prepare_data.py` : conserve **15 proprietes** d'affichage, arrondit les
  coordonnees a 5 decimales (~1,1 m a cette latitude) et les valeurs de trafic
  a l'entier (PLr / length_m a 1 decimale), emet un GeoJSON minifie + gzip.
- `build_v2.py` : reduit a **9 colonnes**
  (`agregId, TVr, TVrmin, TVrmax, DPL, DPLmin, DPLmax, PL, FC`), cast entiers,
  et ajoute les capteurs TV (bleus) / PL (rouges) toggleables.

**Format** : GeoJSON minifie (single-line) + `.gz`, HTML autonome.

**Lancement**
```bash
python scripts/map_2025_light/prepare_data.py
python scripts/map_2025_light/build_v2.py
```

---

## 3. `discontinuity_methodology/` — Detection des discontinuites reseau

**But** : detecter les discontinuites (continuite inter-segments + conservation
aux noeuds) sur le reseau routier oriente type HERE, selon la methodologie
consolidee dans `00_METHODOLOGY.md`.

**Entree -> sortie**
- Entree : `2025.geojson` (**~241 857 aretes, EPSG:4326**), sous
  `Travaux_Python/Travaux_donnees_Lyon/Livrables/`.
- Sorties (dans `scripts/discontinuity_methodology/outputs/`) :
  `discontinuity_edges.geojson`, `discontinuity_nodes.csv`,
  `discontinuity_nodes_full.csv`, `coverage_gaps.csv`, `qc_summary.json`,
  `discontinuity_map.html`, `top_findings.html`, `README.md`.

**Methode (extrait)**
- Grille a 6 paliers de debit pour la continuite inter-segments (AND-of-3 sous
  5 000 veh/j, 2-of-3 au-dessus).
- Seuil `min_flow_required` proportionnel au degre pour la conservation aux
  noeuds ; noeuds de bord isoles dans `coverage_gaps.csv`.

**Format** : GeoJSON, CSV, JSON (QC), HTML (cartes).

**Lancement**
```bash
python scripts/discontinuity_methodology/run_discontinuity_analysis.py
# Mode echantillon (smoke test) :
python scripts/discontinuity_methodology/run_discontinuity_analysis.py --sample 1000
```

---

## Documentation associee

- `docs/data-dictionary.md` : dictionnaire des 26 colonnes cibles standardisees
  (noms, types, unites, synonymes/alias acceptes, retrocompat km/m Bordeaux).
- `scripts/discontinuity_methodology/00_METHODOLOGY.md` : methodologie complete
  de detection des discontinuites.
