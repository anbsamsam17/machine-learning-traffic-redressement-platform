# Rapport de correction — Pipeline TV end-to-end (Playwright)

Contexte : run Playwright sur le pipeline TV avec un GeoJSON Bordeaux (1 961 lignes) a revele
trois bugs bloquants. Ce document fournit le diagnostic complet (root cause, fichier:ligne) et
des fixes prets a appliquer, avec snippets et tests de non-regression.

---

## 1. Diagnostic complet

### 1.1 Probleme A — Dependencies ML manquantes en local

**Symptomes (logs uvicorn) :**
- Thread d'entrainement : `ModuleNotFoundError: No module named 'tensorflow'`
- Generation du rapport eval : `ModuleNotFoundError: No module named 'plotly'`
- Tracebacks secondaires sur `folium` (cartes du rapport HTML).

**Root cause :**
Dans `apps/api/pyproject.toml` (lignes 27-32), les trois packages lourds vivent dans l'extra
`[project.optional-dependencies].prod` :

```toml
[project.optional-dependencies]
prod = [
    "tensorflow-cpu>=2.15,<2.22",
    "plotly>=5.18",
    "folium>=0.15",
]
```

Or ces dependances ne sont PAS optionnelles : `routers/training.py` importe `tensorflow.keras`
au runtime, `routers/evaluation.py` (l. 1242) fait `from tensorflow.keras.models import
model_from_json`, et le helper `_make_folium_map_html` (l. 337) + les barplots utilisent
`plotly`/`folium`. Sans elles, l'API demarre mais TOUT chemin metier crashe.

`pip install -e .` n'installe PAS les extras. Le README (ligne 27) precise bien
`pip install -e ".[dev,prod]"`, mais la double citation et l'extra non-evident pieggent
quiconque copie la premiere moitie de la commande. Le Makefile est absent (`Glob` confirme),
donc aucun garde-fou.

### 1.2 Probleme B — Concatenation `model_dir / model_name` dupliquee

**Reproduction Playwright :**
```
HTTP 404 — Dossier modele introuvable :
  C:\...tmp_workdir\sid\models\elu_lr0.01_..._fmask_111111\elu_lr0.01_..._fmask_111111
                                ^^^^^^ run_name ^^^^^^      ^^^^^^ run_name ^^^^^^
```

**Root cause cote backend** (`apps/api/app/routers/evaluation.py:1200-1207`) :

```python
if body.model_name and body.model_dir:
    model_path = Path(body.model_dir) / body.model_name   # <-- concat
    if not model_path.exists():
        raise HTTPException(status_code=404, ...)
```

Le backend traite `model_dir` comme le **parent** du dossier modele. Meme logique dans
`download_model` (l. 1471).

**Root cause cote contrat API** (`apps/api/app/routers/models.py:65-71, 94-101`) :
`/api/models/list` retourne `ModelInfo.path = str(sub)` ou `sub` est le dossier modele
COMPLET (`.../models/run_name/`), donc le `path` retourne == le path complet, pas le parent.
La meme convention est utilisee pour les uploads (`extract_dir` qui est le parent).

**Root cause cote frontend** (`apps/web/app/(pipeline)/evaluation/page.tsx:140-142`,
identique dans `evaluation-flow.tsx`) :

```ts
const firstPath = modelList[0].path;
const parentDir = firstPath.substring(0, firstPath.lastIndexOf("/"))
               || firstPath.substring(0, firstPath.lastIndexOf("\\"));
setResolvedModelDir(parentDir);
```

Deux defauts :
1. Sur Windows, `lastIndexOf("/")` retourne `-1`, donc `substring(0, -1)` retourne tout le
   path moins le dernier caractere (silently incorrect, le truc le plus pernicieux).
2. Le `||` ne tombe sur la branche `\\` que si la premiere expression est vide (chaine vide),
   pas si elle est tronquee. Le path est donc corrompu et le 404 backend masque le vrai
   probleme.

Le contrat est ambigu : `path` retourne par `list` = chemin complet, mais `model_dir`
attendu par `run`/`download-model` = parent. Le frontend doit deviner et patche cote client.

### 1.3 Probleme C — Documentation install + Docker

**Dockerfile.api (l. 27)** installe correctement `.[prod]` :
```dockerfile
RUN pip install --no-cache-dir --prefix=/install ".[prod]"
```
Donc la prod Docker est OK pour TF/plotly/folium.

Defauts persistants :
- Le builder n'installe PAS `[dev]` (logique pour la prod) mais aucun stage `dev` n'existe
  pour les tests CI dans le meme Dockerfile.
- L'image runtime ne copie PAS le code applicatif via `pip install`, juste via `COPY
  apps/api/ .` (l. 48). Donc `pyproject.toml` est juste un descripteur de deps, pas un
  packaging. C'est OK mais a documenter.
- Pas de Makefile / pas de script `dev-bootstrap.sh` / pas d'invocation `[dev,prod]` dans
  la CI (a verifier dans `.github/workflows/`).
- README ne mentionne pas la cause d'erreur typique en cas d'oubli (`ModuleNotFoundError`).

---

## 2. Fixes recommandes

### 2.1 Fix Probleme A — Promouvoir TF/plotly/folium en deps de base

**Pour / Contre :**

| Option | Pour | Contre |
|---|---|---|
| **(a)** Promouvoir en `dependencies` | Plus de divergence dev/prod, `pip install -e .` suffit, fail-fast a l'import | Image dev plus lourde (~600 MB TF), pas de "lite" install possible |
| **(b)** Garder `[prod]` + Makefile + erreur explicite | Install lite reste possible (ex: CI lint-only) | Pieget recurrent, doc a maintenir |

**Recommandation :** Option (a). TF/plotly/folium ne sont PAS optionnels : sans eux le
backend ne sert a rien. L'extra `[prod]` est un faux marqueur.

**Snippet `apps/api/pyproject.toml` :**

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "python-multipart>=0.0.9",
    "python-dotenv>=1.0",
    "pydantic-settings>=2.0",
    "pandas>=2.1",
    "numpy>=1.24",
    "geopandas>=0.14",
    "pyarrow>=14.0",
    "scipy>=1.11",
    "scikit-learn>=1.3",
    "redis>=5.0",
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    "slowapi>=0.1.9",
    "sentry-sdk[fastapi]>=1.40",
    "prometheus-fastapi-instrumentator>=6.1",
    "email-validator>=2.0",
    "bcrypt>=4.0",
    # ML runtime — required by training/evaluation/report
    "tensorflow-cpu>=2.15,<2.22; platform_machine != 'arm64'",
    "tensorflow>=2.16,<2.22;     platform_machine == 'arm64'",
    "plotly>=5.18",
    "folium>=0.15",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "ruff>=0.4",
    "black>=24.0",
    "mypy>=1.10",
]
```

Le marqueur `platform_machine` resout le commentaire ARM64 du Dockerfile (lignes 11-13).
Supprimer aussi l'extra `[prod]` du `Dockerfile.api` : remplacer `.[prod]` par `.`.

### 2.2 Fix Probleme B — Standardiser le contrat API

**Pour / Contre :**

| Option | Pour | Contre |
|---|---|---|
| **(a)** `model_dir` = path complet, ignorer `model_name` pour path | Aligne avec `path` retourne par `/list`, frontend ne strip plus rien, contrat naturel | Casse retro-compat (eval download URLs externes) |
| **(b)** Documenter `model_dir` = parent + `model_name` = subdir | Code backend inchange | Frontend continue de splitter, fragile sur Windows |

**Recommandation :** Option (a). Le `path` retourne par `/api/models/list` est deja l'URL
canonique du modele ; le contrat doit en faire la verite. `model_name` reste utile pour
l'affichage (`EvalResponse.model_name`) et le filename du ZIP, pas pour la resolution disque.

**Snippet backend `apps/api/app/routers/evaluation.py` (autour de la l. 1200) :**

```python
# Determine model source — model_dir is the FULL path to the model directory.
# model_name is kept purely as a display label (and for the ZIP filename in
# /download-model). We accept the legacy "parent + subdir" form for one release
# by detecting whether body.model_dir already points at a model folder.
if body.model_dir:
    candidate = Path(body.model_dir)
    if (candidate / "NNarchitecture.json").exists() or candidate.suffix == ".keras":
        model_path = candidate                                       # new contract
    elif body.model_name and (candidate / body.model_name).exists():
        model_path = candidate / body.model_name                     # legacy
        logger.warning("Using legacy model_dir+model_name resolution; "
                       "update clients to pass model_dir = full path.")
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Dossier modele introuvable : {candidate}",
        )
    model_name = body.model_name or model_path.name
    try:
        model, norm_raw, training_config = await asyncio.to_thread(
            _load_model_from_dir, model_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

Appliquer le meme switch dans `download_model` (l. 1464-1490) :

```python
@router.get("/download-model")
async def download_model(
    model_name: str = Query(...),
    model_dir: str = Query(...),
    session_id: str = Query(None),
) -> StreamingResponse:
    candidate = Path(model_dir)
    if (candidate / "NNarchitecture.json").exists():
        model_path = candidate
    else:
        model_path = candidate / model_name        # legacy
    if not model_path.is_dir():
        raise HTTPException(404, f"Dossier modele introuvable : {model_path}")
    # ... reste inchange (zip + StreamingResponse)
```

**Snippet frontend `apps/web/app/(pipeline)/evaluation/page.tsx` (l. 137-143)
et `evaluation-flow.tsx` (meme bloc) :**

```ts
if (modelList.length > 0) {
  setSelectedModel(modelList[0].name);
  // New contract: model_dir is the FULL path returned by /api/models/list.
  // Backend no longer concatenates model_name onto it.
  setResolvedModelDir(modelList[0].path);
  toast.success(`${modelList.length} modele(s) de la session`);
}
```

Cote `upload-folder` (l. 195) : aujourd'hui on stocke `data.extract_dir` (== parent). Avec
le nouveau contrat il faut stocker `modelList[0].path` si un modele a ete decouvert.

Mettre a jour la docstring de `EvalRequest.model_dir` (apps/api/app/routers/evaluation.py
l. 37) :
```python
model_dir: str | None = None
"""Full path to the model directory (NNarchitecture.json inside).
Returned by /api/models/list as ModelInfo.path."""
```

### 2.3 Fix Probleme C — Documentation install + Docker

**Actions :**

1. **README.md** — bloc Quickstart, remplacer par :
   ```bash
   cd apps/api
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"          # ML deps now in base, no [prod] needed
   uvicorn app.main:app --reload --port 8000
   ```
   Et ajouter une note :
   > Si `pip install` echoue sur `tensorflow-cpu`, verifier Python 3.11 et plateforme
   > (x86_64 / ARM64). La selection est automatique via marker `platform_machine`.

2. **Dockerfile.api (l. 27)** — supprimer `[prod]` :
   ```dockerfile
   RUN pip install --no-cache-dir --upgrade pip \
       && pip install --no-cache-dir --prefix=/install .
   ```

3. **Ajouter `apps/api/Makefile`** (CREER) :
   ```make
   install:
   	pip install -e ".[dev]"
   test:
   	pytest -q
   smoke:
   	python -c "import tensorflow, plotly, folium, geopandas; print('OK')"
   ```
   Le target `smoke` detecte immediatement les ModuleNotFoundError.

4. **Bootstrap hook FastAPI** (a placer dans `apps/api/app/main.py`, lifespan startup)
   pour fail-fast :
   ```python
   @app.on_event("startup")
   async def _check_ml_deps() -> None:
       missing = [m for m in ("tensorflow", "plotly", "folium")
                  if importlib.util.find_spec(m) is None]
       if missing:
           raise RuntimeError(
               f"Dependances ML manquantes : {missing}. "
               f"Installer avec `pip install -e \".[dev]\"`."
           )
   ```
   Echec en 200 ms au demarrage plutot qu'a la premiere requete training.

---

## 3. Tests de non-regression

### 3.1 Pytest backend — contrat `model_dir`

Ajouter dans `apps/api/tests/test_routers_evaluation.py` :

```python
async def test_eval_run_accepts_full_model_path(
    authenticated_client, csv_content, tmp_path,
):
    """model_dir = chemin complet (nouveau contrat post-correction)."""
    model_dir = tmp_path / "run_a"
    model_dir.mkdir()
    (model_dir / "NNarchitecture.json").write_text("{}")
    (model_dir / "NNnormCoefficients.json").write_text(
        '{"muX":[[0]],"SX":[[1]],"muY":[[0]],"SY":[[1]]}')
    (model_dir / "training_config.json").write_text(
        '{"input_cols":["x"],"output_col":"y"}')
    r = await authenticated_client.post("/api/evaluation/run", json={
        "session_id": "s1",
        "model_name": "run_a",
        "model_dir": str(model_dir),       # full path, NOT parent
    })
    # 400 (no model weights) is fine; 404 with "doubled path" is a regression.
    assert r.status_code != 404 or "run_a\\run_a" not in r.text

async def test_eval_run_legacy_parent_dir_still_works(
    authenticated_client, tmp_path,
):
    """Retro-compat : model_dir = parent + model_name = subdir."""
    parent = tmp_path / "models"
    (parent / "run_a").mkdir(parents=True)
    (parent / "run_a" / "NNarchitecture.json").write_text("{}")
    r = await authenticated_client.post("/api/evaluation/run", json={
        "session_id": "s1",
        "model_name": "run_a",
        "model_dir": str(parent),
    })
    assert r.status_code != 404
```

### 3.2 Smoke test deps ML

Ajouter `apps/api/tests/test_ml_imports.py` :

```python
def test_ml_deps_importable():
    import tensorflow            # noqa: F401
    import plotly                # noqa: F401
    import folium                # noqa: F401
```

Inclure dans le job CI minimal (lint + tests) : si TF n'est pas dans `dependencies`,
ce test echoue tout de suite.

### 3.3 Playwright end-to-end

Reprendre le scenario Bordeaux (1 961 lignes) et asserter :
1. POST `/api/training/start` retourne 202 puis status `running` puis `done` (pas
   `error: ModuleNotFoundError`).
2. `/api/models/list?session_id=...` retourne >= 1 modele avec `path` absolu.
3. POST `/api/evaluation/run` avec `model_dir = <path retourne par /list>` retourne 200,
   pas 404, et `report_url` est non vide.
4. `/api/evaluation/report/{sid}` renvoie un HTML qui contient les chaines
   `plotly` et `folium-map` (presence des deux assets graphiques).

Le test (4) est le filet anti-regression cle : il croise les trois problemes en un seul
trajet utilisateur. Stocker l'artefact `playwright-report/` dans la CI pour audit.

---

## 4. Ordre d'application recommande

1. Promouvoir TF/plotly/folium en base deps (Probleme A) + Makefile + startup check.
   Sans cela, impossible de tester le reste en local.
2. Backend `evaluation.py` : accepter `model_dir` = full path avec fallback legacy.
3. Frontend : passer `path` brut sans split.
4. Mettre a jour le Dockerfile (suppression `[prod]`) + README.
5. Lancer la suite pytest puis le Playwright Bordeaux.

Chaque etape est independante et reversible ; le fallback legacy garantit un deploiement
sans downtime des clients deja en production.
