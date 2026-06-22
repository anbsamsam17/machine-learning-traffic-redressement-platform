# `apps/web` — Frontend MDL Redressement

Interface web de la plateforme de redressement de débits routiers : pipeline d'entraînement/évaluation ML, cartographie interactive et rapports. Application du monorepo Turborepo — voir le [README racine](../../README.md) pour la vue d'ensemble.

## Stack

- **Next.js 16** (App Router) + **React 19**
- **TypeScript 5** en mode `strict` (`tsconfig.json` → `"strict": true`)
- **Tailwind CSS v4** + **shadcn/ui** (`components.json`, `components/ui/`)
- **MapLibre GL** — rendu de réseaux routiers volumineux (12–15k segments) en runtime
- **TanStack React Query** — fetching/cache, hooks métier
- **Zustand** — store global persistant
- **Framer Motion** + **GSAP** — animations (respectant `prefers-reduced-motion`)
- **Recharts** — graphiques d'évaluation

## Structure

```
app/                  # Routes (App Router)
  (pipeline)/         # Flux ML : donnees → config → training → evaluation → extrapolation
  carte/              # Carte de débits (GeoJSON)
  evolution/          # Carte d'évolution des débits
  discontinuites/     # Détection de discontinuités TVr
  visualisation/      # Visualisations
  compteurs/          # Fichier compteurs
  login/  register/   # Authentification
  layout.tsx  providers.tsx  error.tsx  not-found.tsx
components/           # UI réutilisable
  ui/                 # Primitives shadcn/ui + composants visuels
  carte/ map/ charts/ upload/ mapping/ visualisation/ discontinuites/ …
lib/                  # Logique transverse
  api.ts              # Client API typé (ApiError, Bearer JWT, AbortController, 401 centralisé)
  api-url.ts          # Résolution de l'URL de l'API
  auth.ts             # Token, gestion de session expirée
  hooks/              # Hooks React Query (upload, training-status, eval-run, carte-generation…)
  store.ts            # Store Zustand persistant
  map/ map-palette.ts map-style.ts   # Styles & palettes MapLibre
  animations/         # Utilitaires d'animation (prefers-reduced-motion)
  i18n/ content/ types/
```

## Conventions

- **TypeScript strict** : pas de `any` implicite ; les réponses API sont typées et passent par le client de `lib/api.ts`.
- **Accès API** : toujours via `lib/api.ts` (injection du `Bearer` JWT, timeouts `AbortController`, gestion centralisée du 401 → redirection `/login`). Ne pas appeler `fetch` brut depuis les composants.
- **État serveur** via React Query (hooks de `lib/hooks/`) ; **état client** via le store Zustand (`lib/store.ts`).
- **Accessibilité** : respecter `prefers-reduced-motion` pour toute nouvelle animation (helpers dans `lib/animations/`).
- **UI** : composants shadcn/ui dans `components/ui/`, styles Tailwind v4.

## Commandes

```bash
npm run dev      # serveur de développement (http://localhost:3000)
npm run build    # build de production
npm run start    # servir le build
npm run lint     # ESLint (eslint-config-next)
```

L'URL de l'API est lue depuis `NEXT_PUBLIC_API_URL` (cf. `.env.example` à la racine). Depuis la racine du monorepo, `npm run dev` lance web + api en parallèle via Turborepo.
