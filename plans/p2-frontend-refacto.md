# P2 — Plan de refonte CODE Frontend (MDL Redressement Tool v2)

> Scope strict : **architecture, dédup, perf, robustesse, état, API client, types, a11y technique**.
> Hors scope : design system, palette, typo, animations esthétiques (skill UI/UX en parallèle).
> Référence : `audit/03-quality-frontend.md` (note 4.5/10 → cible 8/10).

---

## Vision

Le frontend est une **maquette aboutie posée sur une base en état de démo**. Trois pathologies structurelles :

1. **35 % du code applicatif est dupliqué ou mort** — 681 LOC identiques entre `evaluation/page.tsx` et `extrapolation/page.tsx` (diff = 14 chaînes), logique upload+mapping triplée entre `donnees/`, `carte/`, `compteurs/` (3× ~800 LOC), 3 composants pipeline orphelins, 23/29 composants shadcn jamais importés.
2. **Auth purement cosmétique** — `fetchWithAuth` existe (`lib/auth.ts:34`) mais 36 occurrences brutes de `fetch(apiUrl(...))` / `fetchJSON` / `uploadFile` sortent **sans** header `Authorization`. Middleware bloque les routes UI, l'API est appelée anonymement.
3. **Pas d'architecture data** — 42/42 fichiers `'use client'`, 0 RSC, 0 `next/dynamic`, polling `setInterval(1000)` sans backoff ni cleanup global, 0 `AbortController`, 0 ErrorBoundary, 0 cache HTTP, `sessionStorage` qui s'évapore à la fermeture d'onglet.

Objectif : **purger, factoriser, sécuriser le data layer, industrialiser la résilience** sans toucher au look. Résultat attendu : −240 ko gzip, −2 200 LOC, jobs longs fiabilisés, base saine pour le skill UI/UX.

---

## Bloc A — Dédup massive (P0)

### A1. Factoriser evaluation ↔ extrapolation
- **Fichiers** : `app/(pipeline)/{evaluation,extrapolation}/page.tsx` → créer `components/pipeline/evaluation-flow.tsx`.
- **Description** : `<EvaluationFlow mode="evaluation" | "extrapolation" />` qui paramétrise les 14 chaînes divergentes (titre, label DropZone, nom du ZIP `Rapport_*_${modelName}.html`, toasts). Encapsule `loadModelsFromSession`, `handleFolderSelect`, `handleRun`, useEffect auto-mapping, JSX 4 étapes. Les 2 pages se réduisent à 5 lignes chacune.
- **Pourquoi** : audit §P0-2. 663 LOC // à 97 %, endpoints backend identiques (`/api/evaluation/run`).
- **Effort** : **4 h**. Dépendances : aucune.

### A2. Factoriser upload + mapping (donnees / carte / compteurs)
- **Fichiers** : `app/(pipeline)/donnees/page.tsx`, `app/carte/page.tsx`, `app/compteurs/page.tsx` → créer `lib/hooks/use-upload-and-mapping.ts` + `components/upload/upload-mapping-flow.tsx`.
- **Description** : hook `useUploadAndMapping({ mode, targetColumns, criticalCols, endpoint })` qui expose `{ file, sourceColumns, mappings, previewRows, step, handleFile, handleAutoMap, unmappedCritical }`. Composant `<UploadMappingFlow>` rend DropZone → ColumnMapper → preview avec slots pour spécificités (carte = filtres TVR/DPL, compteurs = colonnes propres).
- **Pourquoi** : audit §Métriques. 3 pages > 800 LOC partagent ~60 % de logique upload ; chaque changement (auto-map heuristics, 413, type fichier) est porté 3×.
- **Effort** : **8 h**. Dépendances : C2 (apiClient injecté en paramètre).

### A3. Dédup résiduelle + types centralisés
- **Fichiers** : tous les `tsx` → créer `lib/types/api.ts`.
- **Description** : `npx jscpd apps/web --min-tokens 50` pour lister tout duplicat restant. Centraliser `UploadResponse`, `ModelInfo`, `EvalMetrics`, `CarteStats`, `CarteModelUploadResponse` (aujourd'hui redéfinis dans `carte/page.tsx` et `compteurs/page.tsx`). Factoriser les 2-3 helpers identifiés.
- **Effort** : **2 h**. Dépendances : A1, A2.

**Total Bloc A : ~14 h. Gain LOC : −1 100.**

---

## Bloc B — Cleanup code mort (P0)

### B1. Supprimer les 3 composants pipeline morts
- **Fichiers** : `components/pipeline/{training-progress,model-comparison,model-detail-drawer}.tsx` (681 LOC).
- **Description** : `git rm`, vérifier zéro import par grep, build.
- **Effort** : **0.5 h**. Dépendances : aucune (quick win immédiat).

### B2. Purger les composants shadcn UI orphelins
- **Fichiers** : `components/ui/{accordion,badge,button,card,checkbox,dialog,dropdown-menu,input,label,popover,progress,scroll-area,select,separator,sheet,skeleton,slider,sonner,switch,table,tabs,textarea,tooltip}.tsx`.
- **Description** : conserver uniquement `gradient-text`, `glow-card`, `neon-button`, `stat-card`, `success-banner`, `tag-input` (les 6 réellement utilisés par le code applicatif).
- **Pourquoi** : audit §Métriques. Maintiennent `@base-ui/react` (~80 ko gzip) pour zéro usage.
- **Effort** : **1 h**. Dépendances : B1.

### B3. Désinstaller les deps orphelines
- **Fichiers** : `package.json`.
- **Description** : `npm uninstall react-hook-form @hookform/resolvers zod jszip @tanstack/react-table @base-ui/react`. Build de vérif.
- **Pourquoi** : audit §P0-3. Bundle gain estimé **~240 ko gzip**.
- **Effort** : **0.5 h**. Dépendances : B1, B2.

**Total Bloc B : ~2 h. Bundle : −240 ko gzip. LOC : −2 200.**

---

## Bloc C — Auth flow réparé (P0)

### C1. apiClient typé centralisé
- **Fichiers** : créer `lib/api-client.ts` ; déprécier `lib/api.ts` et fusionner `fetchWithAuth`.
- **Description** : objet `apiClient` avec `get<T>`, `post<T, B>`, `postForm<T>` (multipart), `stream(path, handlers)` (SSE). Chaque appel injecte : header `Authorization: Bearer ${getToken()}`, `AbortSignal` paramétrable, `timeout` (30 s défaut, 5 min upload, ∞ SSE), handler 401 unifié (`removeToken()` + redirect `/login?session=expired`), retry × 2 backoff `2^n × 500 ms` sur 429/5xx. Types génériques — fin du `Promise<unknown>` de `uploadFile`.
- **Effort** : **3 h**. Dépendances : aucune.

### C2. Migrer les 36 appels bruts → apiClient
- **Fichiers** : `app/login/page.tsx`, `app/register/page.tsx`, `app/(pipeline)/{donnees,config,training,evaluation,extrapolation}/page.tsx`, `app/{carte,compteurs}/page.tsx`, `components/layout/app-header.tsx`.
- **Description** : remplacement mécanique. Supprimer les `as UploadResponse` (générique). Supprimer `lib/api.ts`.
- **Pourquoi** : audit §P0-1. Sans cette migration, l'auth reste cassée.
- **Effort** : **3 h**. Dépendances : C1.

### C3. Refresh token + ErrorBoundary global
- **Fichiers** : `lib/auth.ts` (refresh), `components/error/error-boundary.tsx`.
- **Description** : `refreshIfNeeded()` lit la `exp` du JWT (décodage base64 payload) et appelle `/api/auth/refresh` si < 5 min restantes ; remplace le `max-age=86400` fixe (`auth.ts:16`). ErrorBoundary classe React wrap `children` dans `app/layout.tsx`. Le couplage avec `error.tsx` (Bloc E1) couvre les exceptions de rendu vs runtime.
- **Effort** : **3 h**. Dépendances : C1.

**Total Bloc C : ~9 h.**

---

## Bloc D — Data layer & state (P1)

### D1. Setup TanStack Query
- **Fichiers** : `package.json` (+`@tanstack/react-query` ~10 ko), `app/layout.tsx`, `lib/query-client.ts`.
- **Description** : `QueryClient` avec `{ queries: { staleTime: 30_000, retry: 1 }, mutations: { retry: 0 } }`. Provider client wrappant `children`.
- **Effort** : **1 h**.

### D2. Training : polling → SSE EventSource
- **Fichiers** : `app/(pipeline)/training/page.tsx`, créer `lib/hooks/use-training-stream.ts`.
- **Description** : remplacer `startPolling` (`training/page.tsx:125-213`) par `useTrainingStream(taskId)` basé sur `EventSource` (`/api/training/stream/{task_id}` existe — `apps/api/app/routers/training.py:780`). Auto-reconnect backoff `min(2^n × 500 ms, 30 s)` sur erreur SSE, fallback `useQuery` polling 5 s si 3 échecs successifs. Cleanup `useEffect` ferme l'EventSource au unmount — fini les intervals fantômes (§P1-5).
- **Pourquoi** : audit §P1-5. Setinterval 1 s sans backoff ni cleanup global ; SSE déjà disponible côté backend.
- **Effort** : **4 h**. Dépendances : D1.

### D3. Migrer les autres fetch vers useQuery / useMutation
- **Fichiers** : `evaluation-flow.tsx`, `app-header.tsx`, `donnees/page.tsx`, `carte/page.tsx`, `compteurs/page.tsx`.
- **Description** :
  - `useQuery(['me'], …, { staleTime: 5 * 60_000 })` dans le header → fini le refetch à chaque clic stepper (§P1-8).
  - `useQuery(['models', outputDir], …)` pour `loadModelsFromSession`.
  - `useMutation` pour upload, run-eval, run-training avec `onSuccess: invalidate`.
- **Effort** : **4 h**. Dépendances : C1, D1, A1, A2.

### D4. Cleanup Zustand store + localStorage
- **Fichiers** : `lib/store.ts`.
- **Description** : après D3, beaucoup d'états deviennent inutiles (gérés par TanStack Query). Garder uniquement `mode`, `currentStep`, `sessionId`, `taskId`, `outputDir`. Retirer `territory`, `fileName`. Migrer `storage` vers `localStorage` (§P1-8 : `sessionStorage` perd tout à la fermeture d'onglet).
- **Effort** : **1 h**. Dépendances : D3.

**Total Bloc D : ~10 h.**

---

## Bloc E — Routing & résilience (P1)

### E1. Pages d'erreur et loading
- **Fichiers** : créer `app/{error,not-found,loading}.tsx` + `app/(pipeline)/{error,loading}.tsx`.
- **Description** : composants Next 15 standard, thème dark, bouton « Retour à l'accueil ». `error.tsx` reçoit `error` + `reset` ; afficher `error.digest` si non-prod.
- **Pourquoi** : audit §P1-6. Aujourd'hui un crash ou un 404 sort du thème.
- **Effort** : **1.5 h**.

### E2. Persistance des jobs longs au retour
- **Fichiers** : `lib/hooks/use-training-stream.ts`.
- **Description** : au mount, si `taskId` présent et `status !== completed/failed`, recréer la connexion SSE et restaurer le live stream (aujourd'hui `training/page.tsx:95-114` redémarre via `fetch` ponctuel mais sans reprise de l'historique de logs/loss).
- **Pourquoi** : audit §P1-9.
- **Effort** : **2 h**. Dépendances : D2.

### E3. Mode dans l'URL (deep-link)
- **Fichiers** : `app/(pipeline)/layout.tsx`, `app-header.tsx`, `lib/store.ts`.
- **Description** : remplacer `mode` (store) par `useSearchParams().get('mode')`. URLs deviennent `/donnees?mode=tv`, `/training?mode=pl`. Le titre training (`training/page.tsx:358`) lit le bon mode après refresh ou bookmark.
- **Pourquoi** : audit §P1-9. Bookmarkability et partage cassés.
- **Effort** : **2.5 h**. Dépendances : D4.

**Total Bloc E : ~6 h.**

---

## Bloc F — Bundle & perf (P1)

### F1. Convertir en RSC ce qui peut l'être
- **Fichiers** : `app/page.tsx`, `app/layout.tsx`, `app/{login,register}/page.tsx`.
- **Description** : retirer `'use client'` sur la landing. Extraire les handlers interactifs (ModeCard clicks, LoginForm) en sous-composants `'use client'`. Le wrapper reste RSC.
- **Pourquoi** : audit §P0-4. 42/42 fichiers client, bundle initial gonflé.
- **Effort** : **2 h**.

### F2. `next/dynamic` pour composants lourds
- **Fichiers** : `training/page.tsx` (recharts), `config/page.tsx` (`ConfigForm` 1 185 LOC), `evaluation-flow.tsx` (iframe rapport).
- **Description** : `dynamic(() => import('@/components/charts/loss-chart'), { ssr: false, loading: <Skeleton /> })` — recharts (~95 ko) n'est chargé qu'après la 1re epoch. `dynamic` ConfigForm (chargé uniquement sur `/config`). Idem iframe rapport. Préparer placeholder pour futur viewer carte (maplibre).
- **Effort** : **2 h**.

### F3. Bundle analyzer
- **Fichiers** : `next.config.ts`, `package.json`.
- **Description** : `@next/bundle-analyzer` conditionné `process.env.ANALYZE === 'true'`. Script `npm run analyze`. Mesurer baseline avant/après Bloc B + F.
- **Effort** : **1 h**.

**Total Bloc F : ~5 h.**

---

## Bloc G — TS rigueur & a11y technique (P2)

### G1. ESLint strict + noUncheckedIndexedAccess
- **Fichiers** : `eslint.config.mjs`, `tsconfig.json`.
- **Description** : activer `@typescript-eslint/strict-type-checked` + `stylistic-type-checked`. Dans tsconfig : `noUncheckedIndexedAccess: true`, `noImplicitOverride: true`, `noFallthroughCasesInSwitch: true`. Rattrape par ex. `Object.keys(previewRows[0])` (`donnees/page.tsx:384`).
- **Effort** : **2 h** (fix des warnings inévitables).

### G2. Supprimer les 4 `@ts-ignore webkitdirectory`
- **Fichiers** : créer `types/react-augment.d.ts`.
- **Description** :
  ```ts
  declare module 'react' {
    interface InputHTMLAttributes<T> {
      webkitdirectory?: string;
      directory?: string;
    }
  }
  export {};
  ```
  Retirer les `@ts-ignore` dans `carte/page.tsx:450,460`, et (après A1) dans `evaluation-flow.tsx`.
- **Effort** : **0.5 h**.

### G3. A11y technique + reduced-motion + LazyMotion
- **Fichiers** : `components/pipeline/stepper.tsx`, `training/page.tsx`, `stat-card.tsx`, `app/globals.css`, `app/layout.tsx`.
- **Description** :
  - Stepper : `<nav role="navigation" aria-label="Etapes du pipeline">`, `aria-current="step"` sur le bouton actif, `aria-disabled` sur les futurs.
  - Training : envelopper le `<p>` status et le `StatCard` `bestLoss` dans une région `aria-live="polite" aria-atomic="true"`.
  - `globals.css` : `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; scroll-behavior: auto !important; } }`.
  - `<LazyMotion features={domAnimation} strict>` dans `app/layout.tsx` — économise ~30 ko gzip et bloque l'import implicite de la lib complète (§QuickWin 6).
- **Pourquoi** : audit §P1-7. A11y quasi nulle, 0 garde reduced-motion sur 21 fichiers Framer.
- **Effort** : **2.5 h**.

**Total Bloc G : ~5 h.**

---

## Bloc H — i18n light (optionnel, P3)

### H1. Centraliser les strings FR
- **Fichiers** : créer `lib/i18n/fr.ts` + helper `useT()`.
- **Description** : pas de `next-intl` (overkill pour 5-10 users internes). Module `fr.ts` nesté par feature, helper `t('pipeline.donnees.title')`. Migrer ~80 strings principales (stat cards, toasts, libellés). Prépare une éventuelle `en.ts` sans refonte.
- **Effort** : **3 h**. Différable post-MVP.

---

## Récap effort

| Bloc | Description | Effort (h) | Priorité |
|---|---|---:|:---:|
| A | Dédup massive (eval/extra, upload, types) | 14 | P0 |
| B | Cleanup code mort + deps | 2 | P0 |
| C | apiClient typé + auth + ErrorBoundary | 9 | P0 |
| D | TanStack Query + SSE + store cleanup | 10 | P1 |
| E | error.tsx + persistance jobs + deep-link | 6 | P1 |
| F | RSC + dynamic + analyzer | 5 | P1 |
| G | TS strict + a11y technique | 5 | P2 |
| H | i18n light (optionnel) | 3 | P3 |
| **P0+P1+P2** | | **51** | |
| **+ H** | | **54** | |

À 6 h productives/jour : **~9 jours-homme** (sans H), **~9.5 jours** avec H. Cohérent avec la cible 5-10 jours.

---

## Plan d'exécution séquencé

**Sprint 1 — Hygiène & sécurité (jours 1-3)**
B1, B2, B3 → cleanup mort (2 h). C1 → apiClient (3 h). C2 → migration 36 appels (3 h). C3 → ErrorBoundary + refresh token (3 h). G2 → `@ts-ignore` (0.5 h). E1 → error/loading/not-found (1.5 h).
> Sortie : auth fonctionnelle, bundle allégé, plus d'écran blanc, base saine pour A.

**Sprint 2 — Dédup (jours 4-5)**
A1 → `<EvaluationFlow>` (4 h). A2 → `useUploadAndMapping` + `<UploadMappingFlow>` (8 h). A3 → jscpd + types centralisés (2 h).
> Sortie : −1 100 LOC, fin des bug fixes en double.

**Sprint 3 — Data layer & résilience (jours 6-8)**
D1 → TanStack Query setup (1 h). D2 → hook SSE (4 h). D3 → migration useQuery/useMutation (4 h). D4 → cleanup store + localStorage (1 h). E2 → persistance training au retour (2 h). E3 → mode dans l'URL (2.5 h).
> Sortie : plus de polling brut, plus de leaks d'intervals, deep-link OK, refresh préserve l'état.

**Sprint 4 — Perf & finition (jour 9)**
F1, F2, F3 → RSC + dynamic + analyzer (5 h). G1 → ESLint strict (2 h). G3 → a11y + LazyMotion + reduced-motion (2.5 h).
> Sortie : bundle mesuré, perf optimisée, a11y conforme.

**Sprint 5 — Optionnel (jour 10)**
H1 → i18n light (3 h).

---

## Garde-fou orchestrateur (interaction skill UI/UX)

- **Zéro design touché** : aucune action ne modifie palette, typo, animations esthétiques, layout visuel. Les `motion.*` Framer ne sont pas retirés, seulement encadrés par `LazyMotion strict` et la garde `prefers-reduced-motion`.
- **Conflits potentiels à arbitrer** :
  - Bloc A factorise `<EvaluationFlow>` : si UI/UX réécrit le JSX évaluation/extrapolation, il **doit** travailler sur ce composant unique, pas sur les 2 pages dupliquées. **Pré-requis** : A1 livré avant que UI/UX touche à ces écrans.
  - Bloc B supprime des composants shadcn : si UI/UX en réutilise certains (Dialog, Sheet), figer la liste de suppression avec lui avant B2.
  - Bloc F2 dynamic-import recharts : n'affecte pas l'apparence du graphe, seulement le timing.
- **Hors scope (à confirmer PM)** : remplacement Framer Motion → GSAP (skill UI/UX), maplibre/leaflet pour la carte interactive (feature à part), Storybook (test visuel — utile mais hors scope refacto code).

**Score cible après P0+P1+P2 : 8/10**. Le frontend passe d'une démo cosmétique à une base industrielle où chaque feature ajoutée coûte 1× l'effort au lieu de 2-3×.
