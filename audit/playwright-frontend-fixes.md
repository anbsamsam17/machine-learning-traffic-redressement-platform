# Playwright — Frontend Fixes Post-Test

**Date** : 2026-05-19
**Contexte** : audit déclenché par la session Playwright de bout en bout (login -> upload -> mapping -> training -> eval -> rapport). Deux bugs frontend ont fait échouer le run avant qu'un fix-temp backend ne le débloque. Ce document décrit la remédiation côté `apps/web` — aucun code n'est modifié ici, c'est un plan d'exécution.

---

## 1. Diagnostic

### Problème A — `fetchWithAuth` exporté mais jamais utilisé par les pages

**Root cause.** `apps/web/lib/auth.ts:37-52` définit `fetchWithAuth`, qui est la seule fonction qui injecte explicitement `Authorization: Bearer <token>`. `apps/web/lib/api.ts:29-37` (`buildHeaders`) fait la même chose dans `apiClient.*` et les shims `fetchJSON` / `uploadFile`. **Aucune page de l'arborescence `app/(pipeline)/**`** ne passe par ces helpers — toutes appellent `fetch(apiUrl(...))` brut, sans header. La requête ne porte alors que le cookie `mdl_access_token` (`auth.ts:19`), qui n'est transmis automatiquement qu'en same-origin.

**Conséquence prouvée Playwright.** Pendant le scénario auto-mapping, `POST /api/mapping/auto` (depuis `app/(pipeline)/config/page.tsx:25`) a 401-é parce que `get_current_user` côté API ne lisait que `HTTPBearer`. Un fix-temp backend (cookie fallback) a débloqué, mais l'architecture reste fragile : tout déploiement où l'API est servie sur un sous-domaine différent (api.mdl.io ≠ app.mdl.io) cassera le cookie via la politique SameSite et chaque requête échouera en 401.

**Comptage des callsites bypass.** 26 occurrences de `fetch(apiUrl(...))` réparties sur 6 fichiers (audit `grep` du repo). Aucune n'utilise `fetchWithAuth`.

### Problème B — Contrat API `model_dir` / `model_name` doublonné

**Root cause backend.** `apps/api/app/routers/models.py:46-103` (`_scan_models_in_dir`) construit chaque `ModelInfo` avec `path=str(sub)` où `sub = base.iterdir() entry`. Le `path` retourné est donc le **chemin complet du dossier modèle, suffixe `name` inclus**.

**Root cause frontend.** `apps/web/app/(pipeline)/evaluation/page.tsx:140-142` tente de remonter au parent :
```ts
const firstPath = modelList[0].path;
const parentDir = firstPath.substring(0, firstPath.lastIndexOf("/"))
                  || firstPath.substring(0, firstPath.lastIndexOf("\\"));
```
Mais sur Windows `lastIndexOf("/")` retourne `-1` -> `substring(0, -1)` renvoie une chaîne vide -> fallback OR sur l'autre indexOf. C'est fragile (échoue selon la plateforme du backend). Pire, **lors de l'upload de dossier** (`page.tsx:195`, `:224`), `setResolvedModelDir(data.extract_dir)` est utilisé : `extract_dir` (`apps/api/app/routers/models.py:200`) est `WORKSPACE_ROOT/{session_id}/models/`, c'est-à-dire le **parent** des modèles. Donc l'app envoie tantôt un parent (upload), tantôt un path complet (session-load), de manière incohérente.

**Conséquence prouvée Playwright.** `POST /api/evaluation/run` reçoit `model_dir=C:\...\models\elu_lr0.01_...` et `model_name=elu_lr0.01_...`. Backend `evaluation.py:1202` fait `Path(body.model_dir) / body.model_name` -> `C:\...\models\elu_lr0.01_...\elu_lr0.01_...` -> 404 doublonné. Idem pour `download-model` (`evaluation.py:1471`).

---

## 2. Plan A — Auth header partout

### Listing exhaustif des callsites à migrer

| Fichier | Ligne | Endpoint | Migration cible |
|---|---|---|---|
| `apps/web/components/login/LoginForm.tsx` | 25 | `/api/auth/login` | **laisser tel quel** (pas de token au moment de login) |
| `apps/web/app/(pipeline)/config/page.tsx` | 25 | `/api/mapping/auto` | `apiClient.post` |
| `apps/web/app/(pipeline)/donnees/page.tsx` | 90 | `/api/upload` | `uploadFile` |
| `apps/web/app/(pipeline)/donnees/page.tsx` | 107 | `/api/mapping/auto` | `apiClient.post` |
| `apps/web/app/(pipeline)/donnees/page.tsx` | 221 | `/api/mapping/validate` | `apiClient.post` |
| `apps/web/app/(pipeline)/training/page.tsx` | 99 | `/api/training/status/:id` | `apiClient.get` |
| `apps/web/app/(pipeline)/training/page.tsx` | 131 | `/api/training/status/:id` | `apiClient.get` |
| `apps/web/app/(pipeline)/training/page.tsx` | 294 | `/api/training/start` | `apiClient.post` |
| `apps/web/app/(pipeline)/training/page.tsx` | 335 | `/api/training/cancel/:id` | `apiClient.post` (body vide) |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 108 | `/api/upload` | `uploadFile` |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 132 | `/api/models/list` | `apiClient.get` |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 187 | `/api/models/upload-folder` | `apiClient.postForm` |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 279 | `/api/upload` | `uploadFile` |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 294 | `/api/evaluation/upload-validation` | `apiClient.postForm` |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 304 | `/api/evaluation/run` | `apiClient.post` |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 323 | `/api/evaluation/report/:sid` | `apiClient.get` |
| `apps/web/app/(pipeline)/evaluation/page.tsx` | 364 | `/api/evaluation/download-model` | `apiClient.download` |
| `apps/web/app/(pipeline)/extrapolation/page.tsx` | 108, 132, 187, 279, 294, 304, 323, 364 | (miroir d'evaluation) | idem |
| `apps/web/app/carte/page.tsx` | 214 | `/api/carte/upload-model-folder` | `apiClient.postForm` |
| `apps/web/app/carte/page.tsx` | 348 | `/api/carte/download/:sid` | `apiClient.download` |

**Total : 25 callsites authentifiés à migrer (LoginForm exclu).** Plus l'`EventSource` SSE de streaming training, qui est **un problème connexe** : `EventSource` natif ne permet pas de header `Authorization` — il faudra soit signer l'URL via un query param `?token=`, soit garder le cookie fallback côté backend pour ce stream précis. Hors scope de ce plan.

### Snippet — refactor type (avant / après)

**Avant** (`apps/web/app/(pipeline)/evaluation/page.tsx:304-314`) :
```ts
const evalRes = await fetch(apiUrl("/api/evaluation/run"), {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    session_id: sid,
    model_name: selectedModel,
    model_dir: resolvedModelDir.trim(),
    filter_flag_comptage: filterFlagComptage,
    column_mapping: colMapping,
  }),
});
if (!evalRes.ok) {
  const err = await evalRes.json().catch(() => ({}));
  throw new Error(err.detail ?? "Evaluation echouee");
}
const evalData = await evalRes.json();
```

**Après** (utilise le hook `useEvalRun` existant ou directement `apiClient`) :
```ts
import { apiClient, ApiError } from "@/lib/api";

try {
  const evalData = await apiClient.post<EvalRunResponse>("/api/evaluation/run", {
    session_id: sid,
    model_name: selectedModel,
    model_dir: resolvedModelDir.trim(),
    filter_flag_comptage: filterFlagComptage,
    column_mapping: colMapping,
  });
} catch (e) {
  if (e instanceof ApiError) throw new Error(e.detail);
  throw e;
}
```

Bénéfices : header `Authorization` automatique, redirect `/login` sur 401, `ApiError.detail` typé, timeout 30 s par défaut.

### Effort estimé

- 25 callsites, ~2-5 min/callsite (la majorité sont du simple `fetch -> apiClient.get/post`) : **~2 h**
- Refonte tests Playwright pour vérifier que les headers partent bien : **~1 h**
- Recette manuelle (login -> chaque page) : **~1 h**
- Décision + impl pour le SSE (query param token signé) : **~2 h**
- **Total : 6 h** (1 jour homme avec marge).

---

## 3. Plan B — Contrat API `model_dir` / `model_name`

### Choix recommandé : **parent + name** (statu quo backend, fix frontend)

Le backend `evaluation.py:1202` fait `Path(model_dir) / model_name`, et `download-model` (`:1471`) idem. Ce contrat est cohérent et permet à un utilisateur d'amener un modèle d'ailleurs (saisie manuelle). **Changer ce contrat est plus coûteux** (3 endpoints, code de chargement, validation `security.validate_path`).

La solution est de **renvoyer aussi le `parent_dir`** côté API et de **toujours utiliser `parent_dir` + `name`** côté frontend.

### Snippet backend — `apps/api/app/routers/models.py` (autour de `ModelInfo`)

```python
class ModelInfo(BaseModel):
    name: str
    path: str          # chemin complet — conservé pour rétro-compat
    parent_dir: str    # NOUVEAU : dossier parent (= path à passer à /run et /download-model)
    has_weights: bool
    has_architecture: bool
    has_norm: bool
    training_config: dict[str, Any] | None = None

# dans _scan_models_in_dir, pour chaque modèle trouvé :
models.append(ModelInfo(
    name=sub.name,
    path=str(sub),
    parent_dir=str(sub.parent),   # <— nouvelle ligne
    ...
))
```

### Snippet frontend — `apps/web/app/(pipeline)/evaluation/page.tsx`

```ts
// Remplace lignes 140-142 :
const firstModel = modelList[0];
setResolvedModelDir(firstModel.parent_dir);  // backend autoritative, plus de split fragile

// Lignes 195 + 224 (upload folder) :
// data.extract_dir est déjà le parent_dir d'un modèle, on garde — mais on
// se basera désormais sur model.parent_dir dès qu'il y en a au moins un.
if (modelList.length > 0) {
  setResolvedModelDir(modelList[0].parent_dir);  // homogène entre session-load et upload
}
```

Et étendre le type TS :
```ts
interface ModelInfo {
  name: string;
  path: string;
  parent_dir: string;   // <—
  has_weights: boolean;
  has_architecture: boolean;
  has_norm: boolean;
  training_config?: Record<string, unknown>;
}
```

### Breaking changes & blast radius

- **Backend** : ajout d'un champ optionnel `parent_dir` dans `ModelInfo` -> **non breaking**. Aucun caller existant ne lit ce champ (il n'existe pas encore).
- **Frontend** : remplacement du `substring` fragile + lecture `extract_dir`. Deux fichiers à modifier :
  - `apps/web/app/(pipeline)/evaluation/page.tsx` (lignes 140-142, 195, 224)
  - `apps/web/app/(pipeline)/extrapolation/page.tsx` (miroir, mêmes lignes)
  - Le type `ModelInfo` est défini localement dans chaque page — l'extraire dans `apps/web/lib/types/models.ts` est l'occasion.
- **API contract** `POST /api/evaluation/run` : inchangé (toujours `parent + name`). Donc **0 breaking change** pour des clients existants.
- **Bonus** : ajouter une garde côté backend `evaluation.py:1202` qui détecte le doublon et corrige silencieusement :
  ```python
  model_path = Path(body.model_dir) / body.model_name
  if not model_path.exists() and Path(body.model_dir).name == body.model_name:
      model_path = Path(body.model_dir)  # frontend a déjà mis le chemin complet
  ```
  Filet de sécurité, ~5 lignes, à mettre dans `/run`, `/download-model` et `models.upload-folder`.

**Effort total Plan B : ~1 h 30** (3 fichiers backend + frontend + test Playwright dédié).

---

## 4. Plan C — Session recovery (optionnel)

Le store `apps/web/lib/store.ts:84-90` persiste `sessionId` dans `localStorage` sous `mdl-pipeline-store`. Si l'utilisateur clear cache / change de device, il perd la référence à une session de training de 10+ min toujours active côté serveur.

**Recommandation** : créer `GET /api/sessions/mine` qui renvoie la liste `[{session_id, mode, created_at, last_active, status}]` filtrée par `current_user.id` (JWT). Côté frontend, au mount de `(pipeline)/layout.tsx`, si `useAppStore.sessionId === null`, appeler `apiClient.get("/api/sessions/mine")` et proposer un picker "Reprendre une session active". Persister `user_id` -> `session_id[]` dans Redis (TTL = session TTL). Effort : ~3 h.

---

## 5. Test E2E Playwright — pseudo-code

```text
test("full TV pipeline — login to report", async ({ page }) => {
  // 1. Login
  await page.goto("/login");
  await page.fill('[name="email"]', "test@mdl.io");
  await page.fill('[name="password"]', process.env.PW_TEST_PASSWORD);
  await page.click("button[type=submit]");
  await expect(page).toHaveURL("/");
  // intercept: vérifier que les fetch suivants ont Authorization: Bearer
  page.on("request", req => {
    if (req.url().includes("/api/") && !req.url().includes("/api/auth/login")) {
      expect(req.headers().authorization).toMatch(/^Bearer /);
    }
  });

  // 2. Choisir mode TV
  await page.click("text=Trafic TV");
  await expect(page).toHaveURL(/\/donnees$/);

  // 3. Upload fichier
  await page.setInputFiles('input[type=file]', "fixtures/tv_sample.csv");
  await page.waitForResponse(r => r.url().includes("/api/upload") && r.status() === 200);

  // 4. Mapping auto
  await page.click("text=Mapping auto");
  await page.waitForResponse(r => r.url().includes("/api/mapping/auto") && r.status() === 200);
  await page.click("text=Valider mapping");

  // 5. Config -> Training start (params minimaux)
  await page.goto("/config");
  await page.click("text=Suivant");
  await page.goto("/training");
  await page.click("text=Lancer l'entrainement");
  // Poll status until done — timeout 5 min
  await page.waitForFunction(
    () => document.body.innerText.includes("Termine"),
    { timeout: 300_000 }
  );

  // 6. Evaluation
  await page.goto("/evaluation");
  await page.setInputFiles('input[type=file]', "fixtures/tv_validation.csv");
  // attend le model picker peuplé
  await page.waitForSelector('[data-testid="model-select"] option:nth-child(1)');
  await page.click("text=Lancer evaluation");
  await page.waitForResponse(r =>
    r.url().includes("/api/evaluation/run") && r.status() === 200,
    { timeout: 120_000 }
  );

  // 7. Rapport
  await page.waitForSelector('[data-testid="eval-report-iframe"]');
  const r2 = await page.textContent('[data-testid="metric-r2"]');
  expect(Number(r2)).toBeGreaterThan(0.5);

  // 8. Download model
  const downloadPromise = page.waitForEvent("download");
  await page.click("text=Telecharger modele");
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.zip$/);
});
```

Ce test couvre les deux régressions ci-dessus (auth header + model_dir) et servira de gate CI avant tout merge sur `main`.
