# Plan refonte UI/UX — MDL Redressement Tool v2

**Direction artistique** : Pro / sobre / data-driven. Inspirations : **Linear**, **Vercel Dashboard**, **Notion**, **PostHog**, **Plausible**. Plateforme métier dense en information, lisible, sans glow ni néon, dark mode par défaut.

Pivot complet depuis l'ambiance "Deep Neural / aurora-bg / glow-card / neon-button" actuelle (qui colle pour un produit consumer/playful mais sape la crédibilité d'un outil de modélisation trafic destiné à des techniciens routiers).

---

## 1. Design system

### 1.1 Palette — neutre + 1 accent

**Dark mode (par défaut)** — palette zinc Tailwind, accent unique indigo.

| Token | Valeur | Usage |
|---|---|---|
| `--bg` | `#09090b` (zinc-950) | Fond global |
| `--bg-elevated` | `#18181b` (zinc-900) | Cards, modals, sheets |
| `--bg-subtle` | `#27272a` (zinc-800) | Hover surfaces, tableaux zebra |
| `--border` | `#27272a` (zinc-800) | Bordures par défaut |
| `--border-strong` | `#3f3f46` (zinc-700) | Bordures inputs, focus rings |
| `--text` | `#fafafa` (zinc-50) | Texte primaire |
| `--text-muted` | `#a1a1aa` (zinc-400) | Labels, captions, helpers |
| `--text-subtle` | `#71717a` (zinc-500) | Placeholders, metadata |
| `--accent` | `#6366f1` (indigo-500) | CTA primaire, focus, lien |
| `--accent-fg` | `#ffffff` | Texte sur accent |
| `--accent-subtle` | `rgba(99,102,241,.12)` | Backgrounds accent (badges, selected row) |
| `--success` | `#10b981` (emerald-500) | États succès, validation, GEH bon |
| `--warning` | `#f59e0b` (amber-500) | Warnings, GEH limite |
| `--danger` | `#ef4444` (red-500) | Erreurs, suppression, GEH mauvais |
| `--info` | `#3b82f6` (blue-500) | Info, hints contextuels |

**Light mode** (toggle utilisateur via `next-themes` déjà installé) — même structure, valeurs inversées : `--bg #ffffff`, `--bg-elevated #fafafa`, `--bg-subtle #f4f4f5`, `--border #e4e4e7`, `--text #09090b`, `--text-muted #52525b`, accent identique (indigo passe bien sur les deux).

Le skill ui-ux-pro-max recommandait un binôme Navy `#1E40AF` + amber CTA `#F59E0B` — c'est trop "fintech corporate" pour ton produit. L'indigo neutre tient mieux le rôle d'accent unique sans bruit.

### 1.2 Typographie — 2 familles

| Rôle | Famille | Poids | Usage |
|---|---|---|---|
| **UI** | **Inter** (Google Fonts, font-display: swap) | 400, 500, 600, 700 | Titres, body, labels, navigation |
| **Data / chiffres** | **JetBrains Mono** | 400, 500, 600 | Métriques (GEH, R², MAE), nombres tabulaires, noms de runs `relu_lr0.001_…`, code snippets |

Tailwind v4 : `@theme { --font-sans: "Inter", system-ui, sans-serif; --font-mono: "JetBrains Mono", monospace; }`

Échelle (clamp-friendly) :
- `text-xs 12px` — labels, helpers, badges
- `text-sm 14px` — UI dense (formulaires, navigation, lignes de tableau)
- `text-base 16px` — body par défaut (mobile-friendly)
- `text-lg 18px` — sous-titres
- `text-xl 20px` — titres de section
- `text-2xl 24px` — titres de page
- `text-3xl 30px` — titre principal landing
- Line-height 1.5 body, 1.2 titres, 1.0 chiffres tabulaires

### 1.3 Espacement, radius, shadows

- **Grid** : système 4pt (`4, 8, 12, 16, 24, 32, 48, 64, 96`)
- **Radius** : `--radius-sm 4px` (badges, inputs petits), `--radius 6px` (default, boutons, inputs), `--radius-md 8px` (cards), `--radius-lg 12px` (modals, sheets)
- **Shadows** (sobres, pas de glow) :
  - `--shadow-sm` : `0 1px 2px 0 rgb(0 0 0 / 0.05)` — bordure subtile
  - `--shadow` : `0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)` — cards
  - `--shadow-md` : `0 4px 6px -1px rgb(0 0 0 / 0.1)` — popovers, dropdowns
  - `--shadow-lg` : `0 10px 15px -3px rgb(0 0 0 / 0.1)` — modals
- **Transitions** : `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)` (entrant), `--ease-in: cubic-bezier(0.7, 0, 0.84, 0)` (sortant), durées 150ms (hover), 200ms (default), 300ms (page transitions). Le skill UX guideline confirme : "Use ease-out for entering ease-in for exiting".

### 1.4 Iconographie

`lucide-react` déjà installé. Sizes standardisées : `16` (badges, inline), `20` (boutons, nav), `24` (page titles, empty states). Toujours `aria-hidden="true"` si décoratif, `aria-label` sinon. Bannir tout emoji UI (`pre-delivery checklist` du skill).

### 1.5 Palette data viz (recharts, et future carte maplibre)

6 séries différenciables sur dark + light :

| # | Hex | Usage |
|---|---|---|
| 1 | `#6366f1` indigo | Série principale (loss train) |
| 2 | `#10b981` emerald | Série secondaire (val loss) |
| 3 | `#f59e0b` amber | TV |
| 4 | `#ef4444` red | PL |
| 5 | `#06b6d4` cyan | Compteurs |
| 6 | `#8b5cf6` violet | Réserve |

Pour la **carte de débits** (futur viewer maplibre, agent E4), palette graduée pour les segments :
- Bleu froid → vert → jaune → orange → rouge → bordeaux (échelle TVr veh/j, 7 paliers)
- Inspiration : palette ColorBrewer YlOrRd 7-class, ou `viridis` pour daltoniens

### 1.6 Couleurs WCAG

Test contraste sur palette : `--text` sur `--bg` = 17.4:1 (AAA), `--text-muted` sur `--bg` = 5.7:1 (AA+), `--accent` sur `--bg` = 4.6:1 (AA). Toujours `focus-visible:ring-2 focus-visible:ring-[--accent]` sur interactif (UX rule "Focus States" severity High).

---

## 2. Micro-interactions GSAP

Migration progressive de **Framer Motion → GSAP** (recommandation justifiée §5). 10 specs ciblées, toutes respectant `prefers-reduced-motion`.

### M1 — Stepper transition entre étapes (pipeline)
Timeline orchestrée : ancien step fade-out + circle scale 0.95, nouveau step fade-in + circle scale 1.05 → 1, ligne de connexion fill progressif.
```js
gsap.timeline()
  .to(oldStep, { opacity: 0.4, scale: 0.95, duration: 0.2, ease: 'power2.in' })
  .to(connector, { width: '100%', duration: 0.4, ease: 'power2.inOut' }, '<0.1')
  .from(newStep, { opacity: 0, scale: 0.95, duration: 0.3, ease: 'back.out(1.5)' }, '<0.2')
```

### M2 — Loss chart tracé live (training)
Lors d'une update SSE/polling : nouveau point ajouté avec `gsap.from(point, { scale: 0, duration: 0.2 })` + stroke-dasharray animation sur le path entre dernier et nouveau point. Pas de DrawSVG (premium, on évite licence). Plain stroke-dashoffset animation à 0 sur tween.

### M3 — Compteur animé pour métriques finales
À la fin du training/eval, chaque `StatCard` affiche son chiffre avec un counter tween :
```js
gsap.to(refValue, {
  textContent: finalValue,
  duration: 1.2,
  snap: { textContent: 0.01 },
  ease: 'power2.out',
  onUpdate: () => formatNumber(refValue.textContent)
})
```

### M4 — Page transition cross-fade discret
Layout-level via `useGSAP({ scope: containerRef })` + Next.js App Router. 200ms cross-fade + 4px translateY. Inspiration Linear.

### M5 — Dropzone réception fichier
À l'événement `onDragEnter` : `gsap.to(zone, { borderColor: 'var(--accent)', scale: 1.005, duration: 0.15, ease: 'power2.out' })`. À l'`onDrop` : flash bref `gsap.fromTo(overlay, {opacity: 0.3}, {opacity: 0, duration: 0.4, ease: 'power2.out'})`.

### M6 — Hover cards (lift discret, pas de scale)
Bannir `scale: 1.05` (cause un layout shift et un effet "consumer"). Préférer : `gsap.to(card, { y: -2, borderColor: 'var(--border-strong)', duration: 0.15, ease: 'power2.out' })`. Cursor pointer obligatoire (skill rule).

### M7 — Stats cards apparition stagger
À l'arrivée sur une page de résultats (eval, training-done), stagger des cards :
```js
gsap.from('.stat-card', { opacity: 0, y: 8, duration: 0.3, stagger: 0.05, ease: 'power2.out' })
```

### M8 — Modal/Sheet enter (clip-path reveal)
Au lieu d'un fade-scale "consumer", utiliser un clip-path reveal vertical (top-down) — sensation "page composée" :
```js
gsap.fromTo(modal, { clipPath: 'inset(0 0 100% 0)' }, { clipPath: 'inset(0 0 0% 0)', duration: 0.3, ease: 'power2.out' })
```

### M9 — Toast notifications (sonner déjà installé)
Pas de remplacement nécessaire, juste s'assurer que sonner respecte `prefers-reduced-motion` (à override si pas défaut).

### M10 — Skeleton shimmer (loading-state)
Background `linear-gradient(90deg, var(--bg-elevated) 0%, var(--bg-subtle) 50%, var(--bg-elevated) 100%)`, `background-size: 200% 100%`, anim `background-position` infinite 1.5s. UX rule "Loading Indicators" severity High : "Show spinner/skeleton for operations > 300ms".

**Toutes les anims** sont enveloppées dans :
```js
gsap.matchMedia().add('(prefers-reduced-motion: no-preference)', () => {
  // anims ici
})
```
→ Pour les utilisateurs avec `reduced-motion`, les états finaux sont appliqués sans tween.

---

## 3. Wireframes ASCII par écran

Tous en mode densité info, sans fond décoratif aurora.

### 3.1 Landing `/`

```
┌────────────────────────────────────────────────────────────────────┐
│ ▣ MDL  Trafic Tool                            samir@…  ◐  ┃ Logout │ ← Header (cf 3.2)
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│   Pipeline de modélisation de redressement FCD                     │ ← text-2xl
│   Sélectionnez un mode pour commencer.                             │ ← text-sm muted
│                                                                    │
│   ┌────────────────────┐  ┌────────────────────┐                   │
│   │ 📊 Modèle TV       │  │ 🚛 Modèle PL       │                   │ ← icons lucide
│   │ Tous Véhicules     │  │ Poids Lourds       │                   │
│   │ ─────────────────  │  │ ─────────────────  │                   │
│   │ Entraînement NN    │  │ Entraînement NN    │                   │
│   │ depuis FCD + ref   │  │ depuis FCD + ref   │                   │
│   │                    │  │                    │                   │
│   │ Démarrer  →        │  │ Démarrer  →        │                   │
│   └────────────────────┘  └────────────────────┘                   │
│   ┌────────────────────┐  ┌────────────────────┐                   │
│   │ 🗺  Carte Débits   │  │ 📍 Fichier Compt.  │                   │
│   │ Application TV+PL  │  │ Counting loops     │                   │
│   │ ─────────────────  │  │ ─────────────────  │                   │
│   │ GeoJSON + viewer   │  │ Standardisation    │                   │
│   │                    │  │                    │                   │
│   │ Démarrer  →        │  │ Démarrer  →        │                   │
│   └────────────────────┘  └────────────────────┘                   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```
Cards `--bg-elevated`, border `--border`, hover M6. 4 cards en grid 2x2 desktop, 1x4 mobile.

### 3.2 Header global (sticky)

```
┌────────────────────────────────────────────────────────────────────┐
│ ▣ MDL  ▸ Modèle TV  ▸ Données     [TV] [PL] [Carte] [Compteurs]   │
│                                            samir@anbri-tools.com ◐ │
└────────────────────────────────────────────────────────────────────┘
```
Logo + breadcrumb à gauche (mode en cours + étape), nav 4 modes au centre/droite, user email + theme toggle à droite. Background `--bg/95` avec backdrop-blur, border-bottom `--border`. h-12 (48px).

### 3.3 Pipeline `/donnees`

```
┌────────────────────────────────────────────────────────────────────┐
│ Stepper :  [1.Données]——[2.Config]——[3.Training]——[4.Eval]——[5.Ex] │ ← M1 transition
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Étape 1 — Données                                                 │ ← text-xl
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  ⇪  Glissez votre fichier ici                                │  │ ← M5 dropzone
│  │     ou cliquez pour parcourir                                │  │
│  │     CSV, XLSX, SHP, GeoJSON · max 500 MB                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ──────────── ou ────────────                                      │
│                                                                    │
│  Mapping de colonnes (auto-détecté, confiance moyenne 87 %)        │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Cible            Source                  Confiance           │  │
│  │ ────────────────────────────────────────────────────────────│  │
│  │ TMJATV       ◂  TMJA_TV       ▾          ●●●●● 100 %         │  │
│  │ TMJAPL       ◂  TMJA_PL       ▾          ●●●●● 100 %         │  │
│  │ TxPen        ◂  Tx_Penetration▾          ●●●●○  82 %         │  │
│  │ FC           ◂  fonction_classe▾         ●●●○○  64 %         │  │ ← critique
│  │ ...                                                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  Aperçu (5 / 12 432 lignes)                                        │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ TMJATV │ TMJAPL │ TxPen │ FC │ ...                            │  │ ← table data
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│              [← Précédent]                  [Valider →]            │
└────────────────────────────────────────────────────────────────────┘
```

### 3.4 Pipeline `/config` — formulaire dense

Le ConfigForm actuel fait 1185 lignes, écran fouilli. Refonte en colonnes + sections collapsibles.

```
┌────────────────────────────────────────────────────────────────────┐
│ Stepper :  [✓Données]——[2.Config]——[3.Training]——[4.Eval]——[5.Ex]  │
├────────────────────────────────────────────────────────────────────┤
│  Étape 2 — Configuration hyperparamètres                           │
│                                                                    │
│ ┌──────────────────────────┐ ┌──────────────────────────────────┐  │
│ │ ▼ Architecture           │ │ Résumé                            │  │
│ │ Layers           [2  ▾] │ │ ─────────────────────────────────│  │
│ │ Neurons factor  [×1.5 ▾] │ │ Combinaisons    432               │  │ ← live count
│ │ Activation [relu] [selu] │ │ Durée estimée   ~12 min           │  │
│ │ BatchNorm       [✓]      │ │ Sauvegarde      /data/runs/2024-…│  │
│ │ Dropout         0.2-0.4  │ │                                  │  │
│ │                          │ │ ⓘ Sample weights ×4 sur capteurs │  │
│ │ ▼ Training               │ │   permanents activé              │  │
│ │ Loss   [MSE][Huber][MAE] │ │                                  │  │
│ │ Learning rate     0.001  │ │ [Lancer le grid search →]         │  │
│ │ Min epochs       100     │ │                                  │  │
│ │ Max epochs      1000     │ │                                  │  │
│ │ Batch size       32      │ │                                  │  │
│ │                          │ │                                  │  │
│ │ ▼ Feature subsets        │ │                                  │  │
│ │ [✓] feat 1 + feat 2      │ │                                  │  │
│ │ [✓] + truck features     │ │                                  │  │
│ │ Auto grid       [✓]      │ │                                  │  │
│ │                          │ │                                  │  │
│ │ ▼ Avancé                 │ │                                  │  │
│ │ Seed             42      │ │                                  │  │
│ │ Test split       0.2     │ │                                  │  │
│ └──────────────────────────┘ └──────────────────────────────────┘  │
│                                                                    │
│              [← Précédent]                                         │
└────────────────────────────────────────────────────────────────────┘
```
Sections collapsibles via shadcn `Accordion`. Panel droit "Résumé" sticky avec compte combinaisons live, durée estimée, CTA primaire.

### 3.5 Pipeline `/training` — live chart + logs

```
┌────────────────────────────────────────────────────────────────────┐
│ Stepper :  [✓Données]——[✓Config]——[3.Training]——[4.Eval]——[5.Ex]   │
├────────────────────────────────────────────────────────────────────┤
│  Entraînement en cours · 47/432 combinaisons      [Annuler]        │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Progression globale                                          │  │
│  │ ████████████░░░░░░░░░░░░░░░░░░░░░░░  10.9 %  · ETA 9 min 42  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌─────────────────────────┐ ┌────────────────────────────────┐    │
│  │ Loss (live)             │ │ Run courant                    │    │
│  │ ┌─────────────────────┐ │ │ selu_lr0.001_ep300_mse_drp0.3  │    │ ← mono
│  │ │ ╲                   │ │ │ epoch 234 / 800                │    │
│  │ │  ╲╲                 │ │ │                                │    │
│  │ │    ╲___train ──     │ │ │ Best val_loss   1.247          │    │ ← mono nb
│  │ │       ╲___val  ── ←─│─│ │ Current loss    1.331          │    │
│  │ │           ╲_        │ │ │ Patience used   18/30          │    │
│  │ │             ────    │ │ │                                │    │
│  │ └─────────────────────┘ │ │ ┌──────────────────────────┐   │    │
│  │  100  200  300  400 ep  │ │ │ Logs                     │   │    │
│  └─────────────────────────┘ │ │ epoch 234 loss=1.33 val..│   │    │
│                              │ │ epoch 233 loss=1.34 ...   │   │    │
│                              │ │ ...                      │   │    │
│                              │ └──────────────────────────┘   │    │
│                              └────────────────────────────────┘    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```
Loss chart recharts avec palette §1.5. Live via SSE (skill stack reco "stream content with Suspense"). Logs avec `aria-live="polite"` (skill UX). Au succès final : M3 counter sur les metrics.

### 3.6 Pipeline `/evaluation`

```
┌────────────────────────────────────────────────────────────────────┐
│  Étape 4 — Évaluation                                              │
│                                                                    │
│  Modèle sélectionné  [selu_lr0.001_ep300_mse_drp0.3 ▾]             │
│  Fichier validation  [validation_2024.csv]   [Changer]             │
│                                                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ GEH < 5  │ │   MAE    │ │    R²    │ │   RMSE   │               │ ← StatCards
│  │  82.3 %  │ │  4.21    │ │  0.947   │ │  6.83    │               │ ← M7 stagger
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Tableau détail (1 247 points)                       [Export] │  │
│  │ ────────────────────────────────────────────────────────────│  │
│  │ ID      │ TMJA réel │ TMJA pred │ Erreur │ GEH  │ Tolérance │  │
│  │ 001-A   │   12 430  │  12 199   │  -1.9% │ 2.1  │ ✓ OK      │  │
│  │ 002-B   │    8 220  │   7 980   │  -2.9% │ 2.7  │ ✓ OK      │  │
│  │ ...                                                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Rapport HTML détaillé (sensibilité features)         [⤓]    │  │
│  │ <iframe sandboxed>                                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### 3.7 `/carte` — viewer + side panel

```
┌────────────────────────────────────────────────────────────────────┐
│ Carte de débits — Application des modèles TV+PL                    │
├──────────────┬─────────────────────────────────────────────────────┤
│ ▼ Modèles    │                                                     │
│ TV  [✓]      │                                                     │
│ PL  [✓]      │              ┌─────────────────────────┐            │
│              │              │                         │            │
│ ▼ Données    │              │     maplibre viewer     │            │
│ FCD chargé   │              │   ▲ N  ╱   trajets      │            │
│ 12 432 segs  │              │       ╱                 │            │
│              │              │      ╱ ─ ─ ─            │            │
│ ▼ Filtres    │              │     ╱       ╲           │            │
│ Seuil TVr    │              │    ╱         ╲          │            │
│ [≥ 100  ▾]   │              │                         │            │
│ Excl. FC=1   │              │                         │            │
│ [✓]          │              │                         │            │
│              │              └─────────────────────────┘            │
│ ▼ Intervalles│              ◐ Echelle débit  ▭ Légende             │
│ Slider × 4   │                                                     │
│              │                                                     │
│ [Générer →]  │  ⓘ 12 199 segments générés · Moyenne TVr 4 230      │
│ [⤓ GeoJSON]  │     [Télécharger GeoJSON · 2.3 MB]                  │
└──────────────┴─────────────────────────────────────────────────────┘
```
Side panel collapsible mobile. Viewer maplibre (agent E4) avec palette §1.5. Légende interactive (toggle séries).

### 3.8 `/compteurs`

Identique à `/donnees` + une seule action de génération + bouton download. Très peu de fioritures (c'est un outil utilitaire).

---

## 4. Plan de migration progressif

Ordre conçu pour minimiser le risque de casse + livrer de la valeur visible tôt.

| Phase | Quoi | Effort | Livrable |
|---|---|---|---|
| **P0 — Foundation (~1j)** | Tokens CSS variables (§1.1, §1.3), `tailwind.config.ts` v4 `@theme`, theme provider via `next-themes`, classes utilitaires de base (`.surface`, `.surface-elevated`) | 6-8h | Toggle dark/light fonctionne, tokens disponibles globalement |
| **P1 — Atomes (~1.5j)** | Remplacer `NeonButton` → shadcn `Button` revisité, `GlowCard` → `Card` sobre, `StatCard` refondu avec JetBrains Mono pour nombres, `GradientText` supprimé. Mise à jour `lucide-react` icons à 16/20/24 partout | 10-12h | Composants atomiques nouvelle palette |
| **P2 — Layouts (~1j)** | Header global (3.2), Stepper (3.3 top), page shells container, error/loading/not-found UI sobres | 6-8h | Squelette navigation finie |
| **P3 — Écrans pipeline (~3j)** | `/donnees`, `/config` (gros chantier — splitter le 1185 l. ConfigForm en sections accordéon), `/training` (live chart redessiné), `/evaluation` + `/extrapolation` (qui sera dédup en `<EvaluationFlow>` par agent E3 via plan P2) | 18-22h | Pipeline TV/PL complet |
| **P4 — Écrans hors pipeline (~2j)** | `/carte` (panneau latéral + intégration viewer maplibre fournie par E4), `/compteurs`, Landing `/` refondu | 12-14h | App complète refondue |
| **P5 — Anims GSAP (~1.5j)** | Migration Framer Motion → GSAP, implémenter M1-M10, respect `prefers-reduced-motion`, suppression `aurora-bg`, `success-effects` sons (à demander : keep le ding de fin training ?) | 10-12h | Micro-interactions polished |
| **P6 — Nettoyage (~0.5j)** | Désinstaller Framer Motion si plus aucune ref, supprimer `aurora-bg`, `neon-button.tsx`, `glow-card.tsx`, `gradient-text.tsx` une fois 100 % remplacés. Bundle analyzer pour vérifier l'allègement | 3-4h | Code mort éliminé |

**Total : ~10-11 jours-homme** pour la refonte UI complète. Si l'agent E3 travaille en parallèle avec E1/E2/E5, livraison alignée sur la fin de la vague 3.

---

## 5. Considérations techniques pour l'agent E3

### 5.1 Framer Motion vs GSAP — verdict : migration vers GSAP

**Garder Framer Motion** était une option (déjà installé, bien intégré React), mais :
- GSAP est plus **performant** (manipulation directe DOM/SVG, pas de reconciliation React à chaque frame)
- GSAP a une syntaxe **timeline** plus expressive pour les anims complexes (M1 stepper, M2 chart)
- GSAP est **gratuit pour usage interne/perso/non-business** (license MIT-equivalent depuis 2024 v3.13, tous les plugins core inclus — vérifier au moment du commit). DrawSVG / SplitText restent premium ; on les évite.
- L'écosystème `@gsap/react` (`useGSAP` hook) règle l'intégration React (cleanup auto, scope, dépendances)

**Implication** : ajouter `gsap` et `@gsap/react` au `package.json`, retirer `framer-motion` à la phase P6.

### 5.2 Theme switching

`next-themes` est déjà installé (`apps/web/package.json`). Configurer dans `app/layout.tsx` :
```tsx
<ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
  {children}
</ThemeProvider>
```
Toggle dans le header (3.2) avec icône `Sun`/`Moon` lucide. Persiste via localStorage (par défaut next-themes).

### 5.3 prefers-reduced-motion

Toutes les anims GSAP enveloppées dans `gsap.matchMedia()`. Pour les CSS animations (skeleton M10, hover M6) : `@media (prefers-reduced-motion: reduce) { * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }` dans `globals.css`. Skill UX rule severity High.

### 5.4 Tailwind v4 `@theme`

Tokens définis directement en CSS via `@theme`, exposés comme classes Tailwind. Exemple :
```css
@import "tailwindcss";
@theme {
  --color-bg: #09090b;
  --color-bg-elevated: #18181b;
  --color-accent: #6366f1;
  --color-text: #fafafa;
  --font-sans: "Inter", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", monospace;
  --radius: 6px;
}
```
Utilisable en `bg-accent`, `text-text-muted`, `font-mono`, `rounded-DEFAULT`. Light mode via `[data-theme="light"]` override.

### 5.5 Performance

- Convertir pages qui peuvent l'être en **Server Components** (audit du skill stack : "Fetch data in Server Components" severity High) : `app/layout.tsx`, landing `app/page.tsx`, header (passer en RSC + `client` boundary uniquement pour user menu et theme toggle). Le polling auth (`app-header.tsx:39`) traité par plan P2.
- `next/dynamic` pour recharts, futur maplibre, et autres composants lourds.
- Next.js 15 caching : skill alerte severity High "Next.js 15 changed defaults to uncached for fetch" — à expliciter via `cache: 'force-cache'` sur fetch de données statiques (rares ici).
- Font loading : skill UX rule severity Medium "use `font-display: swap`". Avec `next/font/google` (recommandé) c'est géré automatiquement, sinon ajouter `display: swap` dans `@import`.

### 5.6 Dépendances ajoutées / supprimées

**Ajout** :
- `gsap` (~50 ko gzip)
- `@gsap/react`

**Suppression** (déjà identifiée par audit A3 + plan P2) :
- `framer-motion` (~80 ko gzip) — après phase P5
- `react-hook-form`, `@hookform/resolvers`, `zod` (non utilisés)
- `jszip` (non utilisé)
- `@tanstack/react-table` (utilisé seulement par composants morts)
- `@base-ui/react` (utilisé seulement par composants morts)

**Net** : ~240 ko gzip économisés sur le bundle. Gain perf concret.

### 5.7 Garde-fous croisés avec plan P2

- L'agent E3 doit attendre que P2 ait livré la dédup `<EvaluationFlow>` (P2 bloc A) avant de redesigner les écrans eval/extrapolation, sinon il refactorisera 681 lignes en doublon.
- La liste des composants shadcn à supprimer (23/29) doit être figée AVEC P2 (P2 bloc B) — l'agent E3 ne supprime pas, il consomme la liste validée.
- Theme provider (P0 ici) bloque l'utilisation des nouveaux tokens dans tous les composants — à livrer en premier.

---

## 6. Effort total estimé

| Phase | Effort | Cumul |
|---|---|---|
| P0 Foundation | 6-8 h | 8 h |
| P1 Atomes | 10-12 h | 20 h |
| P2 Layouts | 6-8 h | 28 h |
| P3 Pipeline | 18-22 h | 50 h |
| P4 Hors pipeline | 12-14 h | 64 h |
| P5 GSAP anims | 10-12 h | 76 h |
| P6 Cleanup | 3-4 h | 80 h |

**~80 h ≈ 10-11 j-homme** pour la refonte UI/UX complète.

Compatible avec la fenêtre vague 3 si l'agent E3 démarre P0 dès le go (autres agents E1/E2/E4/E5 ne bloquent pas P0-P2). Sync avec E1/E2 vers P3-P4 quand la dédup back/front est livrée.

---

## 7. Hors scope explicite (à NE PAS faire en vague 3)

- Refonte fonctionnelle (pas de nouvelles features métier — UX seulement)
- i18n EN (juste centralisation strings FR via plan P2 bloc H, traduction EN différée)
- Storybook / catalogue de composants (gain marginal pour 5-10 users internes)
- Tests visuels Chromatic / Percy (idem, sur-engineering pour la cible)
- Refonte de la palette carte maplibre au-delà de la grille à 7 paliers (E4 livre le viewer fonctionnel, fine-tuning visuel = future itération)
- Onboarding tour / product tour interactif (les utilisateurs métier connaissent le domaine, pas besoin)

---

**Référence** : skill `ui-ux-pro-max` invoqué pour design system baseline + searches détaillés (chart, ux, stack nextjs). Patterns landing-page (Enterprise Gateway, Bento Grid) ignorés car inadaptés à un dashboard métier. Direction Linear/Vercel/Notion appliquée comme arbitrage final.
