# Audit qualite frontend - MDL Redressement Tool v2

## Resume executif

Note globale : **4.5 / 10**. Le projet repose sur une stack moderne et coherente (Next.js 15, React 19, TS strict, Tailwind v4, shadcn base-nova, Zustand, Framer Motion, recharts) avec un soin visuel reel (glassmorphism, neon, confetti). Mais sous la couche cosmetique, la base de code est tres mal hygienisee : 35 % du code applicatif est dupliquee ou morte, 85 % des composants UI shadcn scaffoldes ne sont jamais importes, plus de la moitie des dependances declarees ne sont pas utilisees, l'authentification est techniquement cassee (le middleware bloque les routes mais aucune requete API metier ne porte d'`Authorization`), et l'accessibilite est quasi nulle sur les 5 pages metier les plus visibles. Trois problemes structurants : (1) **duplication brutale evaluation/extrapolation - 681 lignes // a 98 %** (un seul `diff` montre 14 chaines changees), (2) **auth cosmetique** - `fetchWithAuth` existe (`apps/web/lib/auth.ts:34`) mais **n'est appelee dans aucune page metier** (les 27 appels `fetch(apiUrl(...))` sortent en clair), et (3) **bundle obese par scaffold mort** - `@base-ui/react`, `@tanstack/react-table`, `react-hook-form`, `@hookform/resolvers`, `zod`, `jszip` totalisent ~450 ko gzip injectes pour zero usage productif.

## Metriques

- **LOC totale frontend** (TSX uniquement) : **6 979 lignes** sur 51 fichiers.
- **Fichiers > 500 lignes** : 5 - `compteurs/page.tsx` (982), `carte/page.tsx` (867), `evaluation/page.tsx` (681), `extrapolation/page.tsx` (681), `training/page.tsx` (600). A eux 5 ils pesent **3 811 lignes soit 54.6 % du frontend**.
- **Doublons stricts** : `evaluation/page.tsx` <-> `extrapolation/page.tsx` = **663 lignes communes sur 681** (97.3 %). Le diff complet montre 14 chaines changees (titres, libelles toasts, nom du fichier ZIP). Tout le code metier (handleRun, loadModelsFromSession, handleFolderSelect, useEffect mapping, JSX des 4 etapes) est strictement identique.
- **Composants morts** : 3 confirmes - `components/pipeline/training-progress.tsx` (247 l), `model-comparison.tsx` (231 l), `model-detail-drawer.tsx` (203 l). **Total 681 lignes orphelines** (zero import detecte par grep). 
- **Composants UI shadcn morts** : sur les 29 fichiers de `components/ui/`, seuls **6 sont reellement importes** par du code applicatif (`gradient-text`, `glow-card`, `neon-button`, `stat-card`, `success-banner`, `tag-input`). Les 23 autres (`accordion`, `badge`, `button`, `card`, `checkbox`, `dialog`, `dropdown-menu`, `input`, `label`, `popover`, `progress`, `scroll-area`, `select`, `separator`, `sheet`, `skeleton`, `slider`, `sonner`, `switch`, `table`, `tabs`, `textarea`, `tooltip`) ne sont referencees que par d'autres composants UI morts. **Volume mort UI : ~2 000 lignes + import de toute la primitive `@base-ui/react`**.
- **Dependances non utilisees** : `react-hook-form` (0 import), `@hookform/resolvers` (0 import), `zod` (0 import), `jszip` (0 import), `@tanstack/react-table` (utilise uniquement par `model-comparison.tsx` mort), `@base-ui/react` (utilise uniquement par les 23 composants UI morts). **Impact bundle estime : ~430-470 ko gzip evitables**.
- **`@ts-ignore` / `@ts-expect-error`** : **4 occurrences** dans 3 fichiers, toutes pour `webkitdirectory` (`carte/page.tsx:450,460`, `evaluation/page.tsx:480`, `extrapolation/page.tsx:480`). Aucune `@ts-nocheck`.
- **`as unknown as`** : 2 occurrences - `success-effects.ts:66` (cast `window` pour `webkitAudioContext`), `training-progress.tsx:66` (cast SSE event - dans composant mort).
- **`'use client'`** : 42 fichiers sur 42 fichiers React. **100 % client** - **aucune RSC**. Le projet n'exploite pas le App Router.
- **ErrorBoundary** : 0. **Pas d'`error.tsx`, pas de `not-found.tsx`, pas de `loading.tsx`** (verifie via Glob `app/**/error.tsx`, `app/**/not-found.tsx`, `app/**/loading.tsx`).
- **`fetchWithAuth`** : exporte dans `lib/auth.ts`, **0 import** dans le code applicatif. Tous les appels API sortent sans header `Authorization`.
- **`AbortController`** : 0 occurrence. Aucun fetch n'est annulable lors d'un unmount.
- **`aria-*`** : 21 occurrences dans 14 fichiers, mais 17 d'entre elles sont dans les composants shadcn UI morts. Sur les 5 pages metier, **0 attribut aria-** explicite (sauf `sr-only` checkbox dans evaluation/extrapolation).
- **`prefers-reduced-motion`** : 0 occurrence. Framer Motion est applique sans garde sur les 21 fichiers qui l'importent.
- **i18n** : 0 librairie (`next-intl`, `react-i18next` absents). Textes FR en dur partout, sans accents (choix volontaire pour eviter encoding cf `apps/web/app/(pipeline)/donnees/page.tsx:242` "Donnees").

## Top 10 problemes priorises

### P0 - 1. Auth cassee : middleware bloque mais API non protegee cote client

`apps/web/middleware.ts:24-44` exige un cookie `mdl_access_token` pour toute route hors `/login`, `/register`, `/_next`, `/api`. **MAIS** : 

- Le middleware **ignore deliberement `/api`** (`middleware.ts:19`).
- `fetchWithAuth` existe dans `lib/auth.ts:34-56` mais **n'est jamais utilise** : `grep -rn "fetchWithAuth"` ne renvoie que la definition. Les 27 appels `fetch(apiUrl(...))` (carte, compteurs, donnees, config, training, evaluation, extrapolation) sortent **sans header `Authorization`**.
- `fetchJSON` (`lib/api.ts:3`) **n'ajoute pas** le token non plus.
- `app-header.tsx:38-39` ajoute le header manuellement uniquement pour `/api/auth/me` - tous les autres appels sont anonymes.

Consequence : si le backend impose JWT (cf le module auth est en place), 100 % des fonctionnalites metier echouent en prod. Si le backend l'a desactive temporairement, n'importe quel visiteur peut appeler l'API. **L'auth est purement cosmetique**.

**Fix** : remplacer toutes les occurrences `fetch(apiUrl(...))` et `fetchJSON` par `fetchWithAuth`. Centraliser via un seul `apiClient` qui injecte le token.

### P0 - 2. Duplication evaluation / extrapolation : 663 lignes strictement identiques

`apps/web/app/(pipeline)/evaluation/page.tsx` (681 l) et `extrapolation/page.tsx` (681 l) diffrent sur **14 chaines** verifiees par `diff -u` : `EvaluationPage` -> `ExtrapolationPage`, "validation" -> "extrapolation", `Rapport_Evaluation_` -> `Rapport_Extrapolation_`, le `description` du DropZone, et 2-3 messages toast. **Toute la logique (handleRun, loadModelsFromSession, handleFolderSelect, useEffect d'auto-mapping, JSX des 7 sections) est strictement dupliquee**. Chaque bug fix doit etre porte 2 fois, chaque evolution doit etre coordonnee 2 fois - et le pire : l'extrapolation reutilise l'endpoint `/api/evaluation/run` et `/api/evaluation/report/{sid}` (identique aux lignes 289, 308), donc fonctionnellement c'est **strictement la meme feature** avec un libelle different.

**Fix** : creer un composant generique `<ModelInferencePage variant="evaluation" | "extrapolation" />` qui parametre les libelles. Gain immediat : -680 LOC, 1 seul endroit pour maintenir.

### P0 - 3. Bundle obese : 6 deps non utilisees + 23 composants UI morts

Le `package.json` declare 18 dependances runtime. Audit reel :

| Dep | Usage | Action |
|---|---|---|
| `react-hook-form` | 0 import | Supprimer |
| `@hookform/resolvers` | 0 import | Supprimer |
| `zod` | 0 import | Supprimer |
| `jszip` | 0 import | Supprimer |
| `@tanstack/react-table` | 1 import (composant mort) | Supprimer apres suppression du composant |
| `@base-ui/react` | 18 composants UI shadcn morts | Supprimer apres purge des composants morts |

**Impact bundle** estime (gzip) : `react-hook-form` ~9 ko + `zod` ~13 ko + `@base-ui/react` ~80 ko + `@tanstack/react-table` ~12 ko + `jszip` ~95 ko + scaffolded UI ~30 ko = **~240 ko gzip** retirables sans toucher a une seule fonctionnalite.

**Fix** : 
1. `npm uninstall react-hook-form @hookform/resolvers zod jszip`
2. `rm components/ui/{accordion,badge,button,card,checkbox,dialog,dropdown-menu,input,label,popover,progress,scroll-area,select,separator,sheet,skeleton,slider,sonner,switch,table,tabs,textarea,tooltip}.tsx`
3. `rm components/pipeline/{training-progress,model-comparison,model-detail-drawer}.tsx`
4. `npm uninstall @base-ui/react @tanstack/react-table`

### P0 - 4. Tout client, aucune RSC, aucun split

Les 42 fichiers React sont **tous** flagges `'use client'`, y compris `app/page.tsx` (landing statique) et `app/layout.tsx`-adjacents. **Aucun `next/dynamic`** detecte. Consequence : 

- Le bundle JS de la home embarque Framer Motion + tout Zustand + tout le header avant l'hydration.
- recharts (~95 ko gzip) est embarque dans le bundle de `training/page.tsx` **et** charge meme si l'utilisateur n'ouvre jamais la page.
- iframe sandbox du rapport HTML d'evaluation (`evaluation/page.tsx:658`) est rendu en client alors qu'il pourrait l'etre cote serveur.

**Fix** : 
- Convertir `app/page.tsx`, `app/login/page.tsx`, `app/register/page.tsx` en RSC (decouper la partie interactive en sous-composant `'use client'`).
- `dynamic(() => import('recharts').then(m => m.LineChart), { ssr: false })` pour la courbe de loss.
- `dynamic(...)` pour `ConfigForm` (1 185 lignes) qui n'est charge que sur `/config`.

### P1 - 5. Polling 1s sans backoff ni cleanup global

`apps/web/app/(pipeline)/training/page.tsx:128` lance `setInterval(..., 1000)` pour poller `/api/training/status/{taskId}`. Problemes :

- Interval fixe a 1 s sans backoff exponentiel : en cas de surcharge serveur, on inonde sans repit.
- Le cleanup `clearInterval(pollingRef.current)` n'est appele que dans les branches `status === "completed"` et `failed` (l.199, 207). **Aucun cleanup `useEffect` global** au unmount du composant : si l'utilisateur clique sur le stepper et quitte `/training` pendant le polling, l'interval continue en background.
- Le bloc `catch` (l.209) avale silencieusement les erreurs reseau - aucun toast, aucun compteur d'echecs successifs.
- Le timer d'`elapsed` (`training/page.tsx:85`) cleanup correctement, mais redemarre a chaque changement de `status` ce qui reset le timer lors du passage `starting` -> `running` (perte de quelques ms - pas dramatique mais pas net).

**Fix** : `useEffect(() => { return () => clearInterval(pollingRef.current); }, [])`. Backoff `1000 * Math.min(2 ** failures, 30)`. Toast `warning` apres 3 echecs successifs.

### P1 - 6. Aucune ErrorBoundary, aucun error.tsx / not-found.tsx

`grep ErrorBoundary` = 0. `Glob app/**/error.tsx` = 0. `Glob app/**/not-found.tsx` = 0. Consequence : 

- Une exception synchrone dans `evaluation/page.tsx` (qui parse `evalData.metrics.r_squared.toFixed(4)` sans guard l.315) -> ecran blanc.
- Une 404 sur `/donnees/wrong` -> page Next.js par defaut, hors du theme dark.
- Un `setReportHtml(null)` puis acces a `reportHtml.length` -> ecran blanc.

**Fix** : ajouter `app/error.tsx`, `app/(pipeline)/error.tsx`, `app/not-found.tsx` avec le theme et un bouton "Retour a l'accueil".

### P1 - 7. Accessibilite quasi nulle sur les pages metier

Audit detaille :

- **Stepper** (`components/pipeline/stepper.tsx`) : `<button disabled={isFuture}>` mais pas de `aria-current="step"`, pas de `role="navigation"` sur le `<nav>`, pas d'announce vocal du step actif. Pour un assistant vocal, on entend juste "1 Donnees, bouton" 5 fois.
- **Training status** : changements de `status` (idle -> running -> completed) n'ont aucun `aria-live="polite"`. Un utilisateur non-voyant ne sait pas que l'entrainement est termine sans recharger.
- **Stat cards** (`StatCard`) : un nombre change avec `animate-success-pulse` flash visuel - mais le `<p>` qui contient la valeur n'est pas dans une region `aria-live`. Aucune indication non visuelle.
- **Loss chart recharts** : aucun `<title>` ni `aria-label` sur le `<svg>`. Pour un screen reader c'est un trou noir.
- **DropZone** (`drop-zone.tsx`) : `<div {...getRootProps()}>` repose sur le keyboard handler de react-dropzone (correct), mais aucun `aria-describedby` reliant la zone aux instructions textuelles.
- **Color contrast** : `text-slate-400` sur `bg-[#080812]` ratio ~3.4:1 - **en dessous du WCAG AA 4.5:1** pour du texte normal. Tres present sur les sous-titres et placeholders.
- **`prefers-reduced-motion`** : 0 garde. Framer Motion `whileHover scale: 1.03` (`NeonButton`), `motion.div animate y: 0` partout - pour quelqu'un qui souffre de vertige, c'est non-conforme.

**Fix prioritaire** : `aria-live="polite"` autour des stat cards de training + sur les toasts d'etat, `aria-current="step"` sur le stepper actif, `@media (prefers-reduced-motion: reduce)` global qui set `transform: none` et reduit les durees.

### P1 - 8. State volatile : sessionStorage + pas de cache API

Le store Zustand (`lib/store.ts:84-92`) persist dans `sessionStorage` uniquement. Consequence : 

- Fermeture d'onglet -> tout perdu (sessionId, taskId, output_dir, training_config).
- Aucune librairie de cache HTTP (`TanStack Query`, `swr`) -> chaque navigation entre `/training` et `/evaluation` relance `loadModelsFromSession` (`evaluation/page.tsx:115`), `fetch(/api/auth/me)` (`app-header.tsx:39`) a chaque changement de `pathname`.
- Le `useEffect` du header re-fetch `/api/auth/me` **a chaque clic sur le stepper** (la liste de deps `[pathname]` change a chaque navigation).
- Si l'utilisateur quitte `/training` avant la fin, perd le polling - le taskId est en sessionStorage mais le composant ne reprend que via `useEffect` initial qui n'a aucun retry.

**Fix** : passer a `localStorage` pour `sessionId`/`taskId` (les seuls necessaires apres refresh), ou TanStack Query avec `staleTime` raisonnable + invalidation sur events.

### P1 - 9. Bookmarkability et deep links cassees

Le route group `(pipeline)` partage les URLs `/donnees`, `/config`, `/training`, `/evaluation`, `/extrapolation` pour 2 modes (TV et PL). Le mode est stocke dans `useAppStore` (sessionStorage). Consequences :

- `https://app/training` bookmarke pour le mode PL -> au refresh, `mode === null`, le titre affiche "Entrainement TV" par defaut (`training/page.tsx:358`).
- Aucun moyen de partager un lien direct vers une session d'entrainement particuliere.
- Le retour navigateur (back) n'est pas lie au stepper - l'utilisateur peut se retrouver sur `/evaluation` avec `currentStep` desynchronise (corrige partiellement par `pathToStep` dans `layout.tsx:10`, mais le store reste pollue).
- Refresh sur `/training` apres un crash du serveur : le `taskId` est rejoue mais s'il n'existe plus cote serveur, on est bloque en `idle` sans message.

**Fix** : `mode` dans l'URL (`/tv/training`, `/pl/training`) ou en query string (`/training?mode=pl`). Stocker `sessionId` et `taskId` aussi en URL pour deep-link.

### P2 - 10. API client primitif : pas de timeout, pas de retry, pas d'abort, pas de types

`lib/api.ts` :

- `fetchJSON` ne supporte pas de `timeout` (un upload de 100 MB peut pendre 5 minutes sans feedback).
- `uploadFile` retourne `Promise<unknown>` (`api.ts:23`) - chaque appelant doit faire un `as UploadResponse` (`carte/page.tsx:235`, `compteurs/page.tsx:280`). Type-safety perdue.
- Aucun `AbortSignal` injecte -> aucun cleanup sur unmount.
- `streamSSE` (`api.ts:41`) ferme la connexion sur **toute** erreur sans retry. Si la connexion SSE coupe a 80 % d'un entrainement de 4 h, l'utilisateur perd la vue temps reel.
- Pas de gestion de 429, 500, 502 -> erreur brute remontee a l'UI.
- Aucun centralisation de `console.error` -> dispersion dans 8 fichiers.

**Fix** : un seul `apiClient` (qui peut etre `ky` ou un wrapper fetch maison) avec `timeout`, `retry: { limit: 2, backoff }`, `signal` propage via les hooks consumers, et des types generiques.

## Plan de refacto front ordonne

### Vague 1 - Hygiene (1-2 jours, gain immediat)

1. Supprimer les 3 composants pipeline morts (`training-progress`, `model-comparison`, `model-detail-drawer`).
2. Supprimer les 23 composants UI shadcn non importes.
3. `npm uninstall react-hook-form @hookform/resolvers zod jszip @tanstack/react-table @base-ui/react`. Verifier que le build passe.
4. Mesurer le bundle avant/apres via `next build` + analyse de `.next/analyze`. Cible : -240 ko gzip.

### Vague 2 - Refactor evaluation/extrapolation (1 jour)

5. Extraire `ModelInferencePage({ variant: 'evaluation' | 'extrapolation' })` dans `components/pipeline/model-inference-page.tsx`.
6. Remplacer `(pipeline)/evaluation/page.tsx` et `extrapolation/page.tsx` par 5 lignes chacun qui appellent le composant generique.
7. Gain : -680 LOC.

### Vague 3 - Auth + API client (1 jour)

8. Centraliser dans `lib/api-client.ts` un fetch wrapper qui : injecte le token via `getToken()`, supporte `AbortSignal`, `timeout`, gere 401 -> redirect login, gere 429/5xx avec retry-after.
9. Remplacer **toutes** les occurrences `fetch(apiUrl(...))` et `fetchJSON` (27 occurrences).
10. Supprimer `fetchWithAuth` et `fetchJSON` redondants.

### Vague 4 - RSC + dynamic split (2 jours)

11. Convertir `app/page.tsx` en RSC, extraire les ModeCard click handlers dans un `<LandingClient />`.
12. `dynamic()` recharts dans `training/page.tsx` (`LineChart` n'est utilise qu'apres 1 epoch).
13. `dynamic()` `ConfigForm` (1 185 LOC).
14. `dynamic()` l'iframe rapport HTML d'evaluation.

### Vague 5 - Robustness (2 jours)

15. Ajouter `app/error.tsx`, `app/(pipeline)/error.tsx`, `app/not-found.tsx`, `app/loading.tsx`.
16. Cleanup global du polling dans `training/page.tsx` via `useEffect` return.
17. Backoff exponentiel + compteur d'echecs sur le polling.
18. ErrorBoundary wrapper sur `ConfigForm` (1 185 LOC = haut risque).

### Vague 6 - Accessibilite + reduced motion (1 jour)

19. `aria-live="polite"` sur les zones de status training + metrics.
20. `aria-current="step"` sur stepper.
21. CSS global `@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }`.
22. Audit contraste : remplacer `text-slate-400` par `text-slate-300` sur tous les textes < 14px.

### Vague 7 - State + cache (2-3 jours)

23. Introduire TanStack Query (10 ko gzip).
24. Migrer `loadModelsFromSession`, `/api/auth/me`, `/api/training/status/*` vers `useQuery`.
25. Ajouter `localStorage` persistence pour `sessionId` et `taskId` uniquement.

### Vague 8 - Deep links + i18n (optionnel)

26. Migrer `mode` du store vers `useSearchParams`.
27. Si i18n requis : `next-intl` minimal pour les libelles UI (5 ko gzip).

**Total** : 10-13 jours dev pour un frontend qui passerait de 4.5/10 a 8/10.

## Quick wins (< 1h)

1. **Supprimer les 3 composants pipeline morts** (`training-progress.tsx`, `model-comparison.tsx`, `model-detail-drawer.tsx`) -> -681 LOC, zero impact runtime, le build passe immediatement.
2. **`npm uninstall react-hook-form @hookform/resolvers zod jszip`** -> -120 ko gzip dans `node_modules`, -4 deps a maintenir, zero impact runtime.
3. **Remplacer les `console.warn`/`console.error` (`evaluation/page.tsx:282,285`, `extrapolation/page.tsx:282,285`) par des `toast.warning`** pour que l'utilisateur sache que le re-upload a echoue.
4. **Ajouter `app/not-found.tsx`** minimal (50 LOC) -> evite la page 404 hors theme.
5. **Renommer le label "Carte de Debits" en "Generation de Carte (GeoJSON)"** sur `app/page.tsx:71` pour ne pas tromper l'utilisateur qui s'attend a une carte interactive (le composant ne fait que generer un GeoJSON telechargeable, aucune lib carto installee).
6. **Wrap le `Framer Motion` global dans un `LazyMotion strict`** dans `app/layout.tsx` -> peut economiser ~30 ko gzip si combine avec `domAnimation` plutot que `m` complet.
7. **Ajouter `aria-live="polite"` sur le `<p>` qui contient le `status` du training** (`training/page.tsx:487`) -> accessibilite +1 sans refacto.
8. **Supprimer le double `setTimeout(() => spawnConfetti(...))` en double** : il est appele 2 fois sur evaluation/extrapolation (l.323-325) sans raison.
9. **Mettre `"strictNullChecks"` explicite dans `tsconfig.json`** : `strict: true` l'inclut deja, mais ajouter `"noUncheckedIndexedAccess": true` pour rattraper les `Object.keys(previewRows[0])` (`donnees/page.tsx:384`) qui supposent qu'`previewRows[0]` n'est pas undefined.
10. **Fix le `// @ts-ignore` `webkitdirectory`** : remplacer par une declaration globale `declare module 'react' { interface InputHTMLAttributes<T> { webkitdirectory?: string; directory?: string } }` -> supprime les 4 `@ts-ignore`.

---

**Verdict** : la maquette est aboutie visuellement mais la base de code est en etat de demo - duplications massives, deps fantomes, auth cosmetique, zero a11y, zero error boundary. Avant tout ajout de fonctionnalite (carte interactive, export PDF, etc.), un nettoyage de 10 jours est imperatif sous peine de doubler les efforts de maintenance a chaque iteration.
