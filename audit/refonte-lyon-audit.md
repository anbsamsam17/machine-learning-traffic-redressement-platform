# Audit Refonte Lyon — Pipeline TV (Etape1_MDL_TV)

Dataset Lyon `BCFCDREF_AllYears_TV.geojson` (3 671 lignes) — schema 26 colonnes
appliquee de bout-en-bout (auto-map 26/26 + training 60 epochs + eval 7,26 MB).

---

## 1. Verdict global

La refonte est correctement cablee bout-en-bout : `mapping.py` produit les 26
colonnes cibles via SYNONYMS, `TV_CONFIG` (services/ml/types.py) declare
les bons `input_cols` + `column_aliases`, `evaluation_pipeline.py` consomme
`type_config.eval_reference_col` de facon parametree. Le run Lyon va jusqu au
rapport HTML.

**Le R²=0.632 n est PAS un bug** mais reflete trois problemes additionnes :
(a) on_off_norm tout-True force `functional_class` (categoriel 1-5) a etre
normalise comme un float continu — perte d info structurelle, (b) 60 epochs
est tres en dessous de la valeur de prod `min_nb_epochs_list=[500,1000]`,
(c) target `TxPen` directe au lieu de `TxPen_brut * coef_Coyote`. Le 0.871
Bordeaux a beneficie d un schema plus simple (6 features all-norm, target
identique, plus d epochs). Verdict : **fonctionnel mais sous-entraine**.

---

## 2. Findings P0 / P1 / P2

### P0-1 — `on_off_norm` mixte casse l eval (shape mismatch 6 vs 7)

**Fichier :** `apps/api/app/services/ml/normalize.py:32-39`,
`apps/api/app/services/ml/training_pipeline.py:393`,
`apps/api/app/routers/evaluation.py:1337-1338`.

**Root cause :** `normalize()` calcule `mu = mean(x[:, on_off_norm])` — la taille
de `mu_x` egale `sum(on_off_norm)` (6 pour TV par defaut), pas `len(input_cols)`
(7). Le pipeline sauvegarde `muX/SX` de taille 6 dans `NNnormCoefficients.json`.
A l eval, `run_evaluation` fait `(X - x_mean) / x_std_safe` sur `X` shape
(3671, 7) contre `x_mean` shape (6,) — broadcast crash. Le fix partiel deja
applique a `_build_sensitivity_section_html` (l.497-508) ne couvre PAS le path
principal.

**Snippet de fix (evaluation.py, juste apres l.1237) :**
```python
# Expand norm vectors to full input width if training masked some columns
on_off = training_config.get("on_off_norm")
if on_off is not None and len(on_off) == len(input_cols) and len(x_mean) < len(input_cols):
    mask = np.array(on_off, dtype=bool)
    full_mu = np.zeros(len(input_cols), dtype=np.float64)
    full_sd = np.ones(len(input_cols), dtype=np.float64)
    full_mu[mask] = x_mean
    full_sd[mask] = x_std
    x_mean, x_std = full_mu, full_sd
    norm_mask = mask          # store for predict
else:
    norm_mask = np.ones(len(input_cols), dtype=bool)
```
puis remplacer `X_norm = (X - x_mean) / x_std_safe` (l.1338) par
```python
x_std_safe = np.where(x_std == 0, 1.0, x_std)
X_norm = X.copy()
X_norm[:, norm_mask] = (X[:, norm_mask] - x_mean[norm_mask]) / x_std_safe[norm_mask]
```

**Impact :** Unblock le mode prod par defaut (`TV_CONFIG.on_off_norm` est
mixte). **Effort : 1h** (incl. test).

---

### P0-2 — `evaluation.py` saupoudre 30+ refs hardcodees a `TMJABCTV`/`TMJAFCDTV`

**Fichier :** `apps/api/app/routers/evaluation.py`. Grep complet :

| Ligne | Reference | Contexte |
|------|-----------|----------|
| 197-200, 228-242 | `TMJABCTV` | `_LEGACY_compute_flow_metrics` (mort, sera vire) |
| 268-323 | `TMJABCTV`, `TMJAFCDTV` | `_make_barplot_html` titles + hover |
| 287, 290, 314-315 | `TMJABCTV`, `TMJAFCDTV` | barplot traces |
| 370 | `["TMJOBCTV", "TMJABCTV"]` | OK — guard deja applique |
| 403, 406, 428, 452 | `TMJAFCDTV`, `TMJABCTV` | folium popups + legend |
| 489, 524 | `TMJAFCDTV`, `TMJATV` | sensitivity docstring + numerator |
| 742, 751, 845 | `TMJABCTV` | `_generate_html_report` summary tables |
| 1006, 1018 | `TMJABCTV` | titres HTML hardcoded |
| 1144-1149, 1290-1292 | aliases | `TMJATV->TMJAFCDTV` (legacy mapping) |
| 1159-1163 | `TMJAFCDTV`, `TMJABCTV` | case-insensitive recovery |
| 1351-1397 | `TMJAFCDTV`, `TMJABCTV` | calcul TVr + Erreur + GEH |

**Fix prefere :** importer `TV_CONFIG`/`PL_CONFIG` en haut du fichier et
parametrer toutes les colonnes :
```python
from ..services.ml.types import TV_CONFIG, PL_CONFIG

def _cfg(training_config):
    return PL_CONFIG if (training_config or {}).get("model_type", "TV").upper() == "PL" else TV_CONFIG

# dans _make_folium_map_html, _make_barplot_html, _generate_html_report :
ref_col = cfg.eval_reference_col           # "TMJOBCTV" Lyon, fallback "TMJABCTV" via aliases
fcd_col = cfg.eval_numerator_fcd           # "TMJOFCDTV"
```
Ajouter en debut de `run_evaluation` un passage de normalisation des noms via
`TV_CONFIG.column_aliases` AVANT toute eval :
```python
for old, new in cfg.column_aliases.items():
    if old in df.columns and new not in df.columns:
        df[new] = df[old]
```
Puis n utiliser que les noms canoniques (TMJOBCTV / TMJOFCDTV / TxPen) dans
TOUT le module. Supprimer `_LEGACY_compute_flow_metrics` (l.226-258) en
priorite — code mort qui n est plus appele depuis B3 (l.219-223).

**Impact :** Bordeaux passe encore (alias TMJABCTV->TMJOBCTV resolu via
`column_aliases`), Lyon devient natif. **Effort : 3h** (refactor + tests).

---

### P1-3 — R² 0.632 Lyon : causes ML

**Diagnostic :**
1. `functional_class` (1-5) avec `on_off_norm=True` forcage : la valeur entiere
   est centree-reduite comme un float continu. Le reseau apprend une relation
   monotone bidon entre FC=1 (autoroute) et FC=5 (rue) au lieu d apprendre
   5 categories disjointes.
2. `max_epochs=60` est aberrant — `TV_CONFIG.default_min_nb_epochs=500-1000`.
3. La cible Lyon est `TxPen` (col mappee de `TxPen_brut * coef_Coyote` ou simple
   `TMJOFCDTV/TMJOBCTV*100` selon le fichier source). A clarifier dans
   `mapping.py:275-280` : la derivation est faite que si `TxPen.isna().all()`,
   donc si le GeoJSON Lyon a deja une colonne `TxPen`, on prend la valeur
   ambigue sans appliquer `coef_Coyote`.
4. analysis_scope="all" => train+test confondus, R² gonfle artificiellement.
   Si R²=0.632 sur le full set inclut le train, le R² test reel est PIRE.

**3 axes prioritaires (par ordre de gain attendu) :**

**A. One-hot `functional_class`** (gain estime +0.05 a +0.10 R²)
```python
# dans services/ml/data_prep.py, avant la separation train/test :
if "functional_class" in df.columns:
    fc = pd.to_numeric(df["functional_class"], errors="coerce").fillna(0).astype(int).clip(1, 5)
    for k in range(1, 6):
        df[f"fc_{k}"] = (fc == k).astype(int)
    # remplace dans input_cols : functional_class -> [fc_1..fc_5]
```

**B. Augmenter `min_nb_epochs_list` a [200, 500]** et activer early-stopping
sur val_loss. Le frontend doit exposer ces controles + un toggle "training
rapide vs prod".

**C. analysis_scope="valid_only"** par defaut + split 80/20 sample-stratifie sur
flag_comptage. Re-evaluer sur le subset valid uniquement pour avoir un R² test
honnete.

**Effort : 6h** (one-hot + scope + UI controls).

---

### P1-4 — Cible `TxPen` : formule ambigue

**Fichier :** `apps/api/app/routers/mapping.py:275-280`.

```python
if "TxPen" in df.columns and df["TxPen"].isna().all():
    tmjofcd = pd.to_numeric(df.get("TMJOFCDTV"), errors="coerce")
    tmjobc  = pd.to_numeric(df.get("TMJOBCTV"), errors="coerce")
    df.loc[mask, "TxPen"] = (tmjofcd[mask] / tmjobc[mask] * 100.0).round(4)
```

Etape1_MDL_TV.txt l.28 dit `TxPen = TxPen_brut × coef_Coyote`. Le fichier
Lyon a deja `TxPen_brut`. **Fix recommande :** ajouter
```python
if "TxPen" in df.columns and df["TxPen"].isna().all():
    if {"TxPen_brut", "coef_Coyote"}.issubset(raw_df.columns):
        df["TxPen"] = pd.to_numeric(raw_df["TxPen_brut"], errors="coerce") \
                    * pd.to_numeric(raw_df["coef_Coyote"], errors="coerce")
    else:
        # fallback TMJOFCDTV/TMJOBCTV * 100 (deja en place)
```
+ logger.info quelle formule a ete utilisee. **Effort : 1h.**

---

### P2-5 — Contrat API `model_dir`/`model_name` toujours divergent

**Fichier :** `apps/api/app/routers/models.py:67`,
`apps/web/app/(pipeline)/evaluation/page.tsx:138-142`.

`/api/models/list` renvoie `path = str(sub)` (chemin complet `…/models/elu_lr…`)
et le frontend doit reconstruire `model_dir` par bricolage regex
(`firstPath.substring(0, firstPath.lastIndexOf("/"))`). Pas robuste sur
Windows + double-separator + bug si nom contient `/`.

**Fix backend (preferable) :** ajouter `parent_dir` cote API.
```python
# models.py:24-30
class ModelInfo(BaseModel):
    name: str
    path: str
    parent_dir: str            # nouveau : ce que /evaluation/run attend
    has_weights: bool
    has_architecture: bool
    has_norm: bool
    training_config: dict[str, Any] | None = None
```
puis `parent_dir=str(base)` pour les models scannes. Frontend devient
`setResolvedModelDir(modelList[0].parent_dir)` — fini la regex.

**Impact :** Cosmetic mais elimine une classe de bugs Windows. **Effort : 30min.**

---

## 3. Ameliorations ML recommandees

| # | Ameliroation | Fichier | Effort | Gain attendu |
|---|------|---------|--------|--------------|
| 3.1 | Fix on_off_norm mixte end-to-end (cf. P0-1) | normalize.py / evaluation.py | 1h | Debloque prod |
| 3.2 | One-hot `functional_class` (5 features `fc_1`..`fc_5`) | data_prep.py + types.py TV_CONFIG.input_cols | 2h | +0.05-0.10 R² |
| 3.3 | Clarifier TxPen = TxPen_brut × coef_Coyote (P1-4) | mapping.py | 1h | Coherence |
| 3.4 | Augmenter neurons_factors `[[1.0, 1.0]]` -> grid `[[1.0,1.0],[2.0,1.0],[2.0,2.0]]` | TrainingConfig | 0.5h | +0.02 R² |
| 3.5 | Default `min_nb_epochs_list=[200, 500]` + early-stop sur val_loss patience=50 | training_pipeline.py | 1h | +0.05 R² |
| 3.6 | `analysis_scope="valid_only"` par defaut + test_size=0.2 force | TrainingConfig | 0.5h | Verite epistemique |
| 3.7 | Sample weighting flag_comptage : checker que w=4 est applique vraiment | training_pipeline.py | 1h | +0.02 R² capteurs perm. |
| 3.8 | Eviter zero-division dans TxPen derivation (`mask = tmjobc > 10`) | mapping.py | 0.5h | Qualite target |
| 3.9 | Log + plot dans le rapport HTML : R² train / R² test separes | evaluation.py | 2h | Verite epistemique |

---

## 4. Ameliorations UI / UX

| # | Item | Fichier |  Effort |
|---|------|---------|---------|
| 4.1 | Bouton "Valider et generer la table" : afficher `(26 + N extras)` au lieu du label generique | `apps/web/components/pipeline/upload-mapping-flow.tsx:303` | 0.5h |
| 4.2 | Section UI dediee "Variables additionnelles" dans ColumnMapper : liste des `extra_candidates` retournes par `/api/mapping/auto` avec checkbox + `extra_cols` envoye dans `/validate`. Aucun code frontend n appelle `extra_cols` actuellement (grep vide) | `components/pipeline/upload-mapping-flow.tsx`, `components/ColumnMapper.tsx` | 4h |
| 4.3 | Renommer titre header "ML Redressement FCD TV" -> "ML : Redressement FCD Tous Vehicules" (coherent avec landing.ts l.25) | `apps/web/components/layout/app-header.tsx:26` | 5min |
| 4.4 | Migrer `/carte` et `/compteurs` au schema 26 cols : remplacer `REQUIRED_COLUMNS` (TMJATV / car_average_distance_km / TMJAVL / linkFC) par les noms canoniques TMJOFCDTV / avg_distance_m / functional_class | `apps/web/app/carte/page.tsx:79-90`, idem compteurs | 3h |
| 4.5 | Afficher dans la card Eval le `R² train` ET `R² test` quand training_config contient un test_size>0 | `apps/web/app/(pipeline)/evaluation/page.tsx` | 1h |
| 4.6 | Tooltip explicatif sur le bouton "Lancer le training" : nombre de combinaisons + estimation duree | `apps/web/app/(pipeline)/training/page.tsx` | 1h |

---

## 5. Tests pytest a ajouter

A creer dans `apps/api/tests/test_refonte_lyon.py` :

```python
# 1. Auto-map Lyon : 26/26 colonnes avec 24 exact + 2 synonym
def test_automap_lyon_geojson():
    df = pd.read_file("fixtures/BCFCDREF_AllYears_TV_sample.geojson")
    mappings, extras = _auto_map(list(df.columns))
    confidences = Counter(m.confidence for m in mappings)
    assert confidences["exact"] >= 24
    assert confidences["synonym"] >= 2
    assert confidences["missing"] == 0

# 2. Validate Lyon avec extras : extra_cols copies dans learning_df
def test_validate_lyon_with_extras():
    raw_df = pd.read_file("fixtures/lyon.geojson")
    mapping = {t: t for t in TARGET_COLUMNS if t in raw_df.columns}
    extras = ["FRC_BIT", "DIR_TRAVEL"]
    df, _, _ = _build_learning_df(raw_df, mapping, extra_cols=extras)
    assert "FRC_BIT" in df.columns and "DIR_TRAVEL" in df.columns
    assert len(df.columns) == 26 + 2 + 1   # +1 flag_comptage

# 3. Train Lyon (smoke) : on_off_norm mixte ne crash plus
def test_train_lyon_mixed_norm():
    cfg = {"input_cols": TV_CONFIG.input_cols,
           "output_cols": ["TxPen"],
           "on_off_norm": [True]*6 + [False],
           "max_epochs": 5, "min_nb_epochs_list": [3]}
    artifacts = run_training(df=lyon_df, config=cfg, type_config=TV_CONFIG)
    art = next(iter(artifacts.values()))
    assert len(art.mu_x) == 6                    # sum(on_off_norm)
    assert art.training_config["on_off_norm"] == [True]*6 + [False]

# 4. Eval Lyon : pas de crash shape mismatch
def test_eval_lyon_mixed_norm(tmp_path):
    # train + serialise un mini modele on_off mixte, run /api/evaluation/run
    # assert response.status_code == 200 et metrics.R2 is finite
    ...

# 5. Retrocompat Bordeaux : TMJATV->TMJOFCDTV via synonymes
def test_retrocompat_bordeaux_synonyms():
    bordeaux_cols = ["TMJATV","TMJAPL","car_average_speed_kmh","car_average_distance_km",
                     "truck_average_speed_kmh","truck_min_average_distance_km","linkFC","TMJABCTV"]
    mappings, _ = _auto_map(bordeaux_cols)
    by_target = {m.target: m for m in mappings}
    assert by_target["TMJOFCDTV"].source == "TMJATV"
    assert by_target["functional_class"].source == "linkFC"
    assert by_target["avg_speed_kmh"].source == "car_average_speed_kmh"
```

Fixtures : extraire 100 lignes de `BCFCDREF_AllYears_TV.geojson` Lyon + 100
lignes Bordeaux dans `apps/api/tests/fixtures/`.

**Effort total tests : 4h** (incl. fixtures).

---

## 6. Sommaire chiffre

| Priorite | Items | Heures | Cumul |
|---------|-------|--------|-------|
| **P0** (bloquant) | P0-1 norm mixte (1h) + P0-2 hardcoded refs (3h) | **4h** | 4h |
| **P1** (qualite ML) | P1-3 functional_class one-hot + epochs + scope (6h) + P1-4 TxPen formula (1h) | **7h** | 11h |
| **P2** (clean) | P2-5 model_dir contract (0.5h) + 4.3 titre (0.1h) + 3.4/3.5/3.6/3.8 hyperparams (2.5h) | **3h** | 14h |
| **UX** | 4.1 bouton (0.5h) + 4.2 extras UI (4h) + 4.4 carte/compteurs (3h) + 4.5/4.6 (2h) | **9.5h** | 23.5h |
| **ML quality push** | 3.2/3.7/3.9 (5h) | **5h** | 28.5h |
| **Tests** | 5 cas pytest + fixtures | **4h** | **32.5h** |

**Total : ~33h soit ~4 jours-homme.**

Sequencage recommande : P0 (1j) -> tests baseline (0.5j) -> P1 + ML quality (2j)
-> UX extras + migration carte (1j) -> P2 et nettoyage (0.5j). Mesurer R² sur
Lyon apres chaque etape pour valider que l on remonte vers 0.85+.
