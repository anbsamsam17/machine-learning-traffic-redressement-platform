# Design Spec — Carte des volumes de trafic 2025 (Grand Lyon)

Source : `2025_light.geojson` (98 129 LINESTRING, EPSG:4326, 81 MB).
Cible : page HTML standalone, MapLibre GL JS, hors-ligne après chargement.

---

## 1. Palettes de couleurs (7 classes)

Schéma jaune clair -> brun rouge, fidèle au screenshot Compass.

### TVr — TV, véh/j par sens
| Classe | Hex | Label | % attendu |
|---|---|---|---|
| > 10 000 | `#7a1f0f` | Supérieur à 10 000 | ~6 % |
| 6 000 – 10 000 | `#c0341d` | Entre 6 000 et 10 000 | ~8 % |
| 4 000 – 6 000 | `#e85b1a` | Entre 4 000 et 6 000 | ~10 % |
| 2 000 – 4 000 | `#f08a1f` | Entre 2 000 et 4 000 | ~15 % |
| 1 000 – 2 000 | `#f5b04a` | Entre 1 000 et 2 000 | ~18 % |
| 500 – 1 000 | `#f5cf6e` | Entre 500 et 1 000 | ~16 % |
| < 500 | `#f7e7a1` | Inférieur à 500 | ~27 % |

Bornes (JS) : `[500, 1000, 2000, 4000, 6000, 10000]`.

### DPL — PL, véh/j par sens
PL ~10 % du TV. Bornes adaptées pour conserver une distribution proche du TVr.
| Classe | Hex | Label | % attendu |
|---|---|---|---|
| > 1 000 | `#7a1f0f` | Supérieur à 1 000 | ~5 % |
| 600 – 1 000 | `#c0341d` | Entre 600 et 1 000 | ~7 % |
| 400 – 600 | `#e85b1a` | Entre 400 et 600 | ~9 % |
| 200 – 400 | `#f08a1f` | Entre 200 et 400 | ~14 % |
| 100 – 200 | `#f5b04a` | Entre 100 et 200 | ~18 % |
| 50 – 100 | `#f5cf6e` | Entre 50 et 100 | ~17 % |
| < 50 | `#f7e7a1` | Inférieur à 50 | ~30 % |

Bornes (JS) : `[50, 100, 200, 400, 600, 1000]`.

---

## 2. Panneau Légende (top-left, fixed)

```
┌─────────────────────────────┐
│  [ TVr ⚪──● DPL ]          │  toggle switch
│  TVr (TV) en véh/j          │  title (16px bold, #ffffff)
│  par sens                   │  subtitle (12px, #9aa3b2)
│  ─────────────────────────  │
│  ▬  Supérieur à 10 000      │  swatch 24×6 px, radius 2
│  ▬  Entre 6 000 et 10 000   │
│  ▬  Entre 4 000 et 6 000    │
│  ▬  Entre 2 000 et 4 000    │
│  ▬  Entre 1 000 et 2 000    │
│  ▬  Entre 500 et 1 000      │
│  ▬  Inférieur à 500         │
│  ─────────────────────────  │
│  Source : MDL 2026           │
└─────────────────────────────┘
```
- Background `#0f1424`, opacity 0.92, border-radius 12 px, padding 16 px, box-shadow `0 4px 24px rgba(0,0,0,.35)`.
- Texte : `#ffffff` (titres), `#cdd3df` (labels), `#9aa3b2` (notes).
- Police : `'Inter', -apple-system, system-ui, sans-serif`.
- Largeur fixe 260 px desktop ; sur mobile (<768 px) replié derrière bouton ☰ flottant.
- **Clic sur un swatch** : toggle visibilité de la classe (état grisé + `text-decoration: line-through`, MapLibre `setFilter` exclut la classe).
- Toggle TVr/DPL : pill 56×24 px, accent `#22d3ee`, animation 200 ms.

---

## 3. Style des lignes

- **Couleur** : MapLibre `case` sur `TVr` (ou `DPL`) selon bornes ci-dessus.
- **Largeur (px)** : interpolation linéaire par classe + zoom.
  - Formule : `width = base[class] * (1 + (zoom - 11) * 0.25)` clampée à [0.4, 6].
  - `base[class]` : `[0.6, 0.9, 1.3, 1.8, 2.4, 3.2, 4.0]` du plus bas au plus haut.
- **Opacité** : `0.7` par défaut ; tronçons d'une classe filtrée -> `0` via `setFilter`.
- **Line cap / join** : `round` / `round`.
- **Hover** : `line-opacity = 1.0`, `line-width = base + 1`, cursor `pointer`. Géré via `mousemove` + feature-state.
- **Sélection (post-click)** : surcouche `#22d3ee` avec halo blanc 1 px (deux layers empilés).

---

## 4. Popup au clic

Style : carte flottante 320 px, fond `#ffffff`, ombre douce, radius 10 px, padding 14 px.

```
agregId : 7f3a-…-c12       [×]
─────────────────────────────
TVr   12 450 véh/j
      (entre 11 800 et 13 100)

DPL   1 120 véh/j
      (entre 980 et 1 240)

PL    1 120 véh/j  •  PLr 9.0 %
─────────────────────────────
FC 3 · n_merged 4 · 312 m
FUNC_CLASS : 3  ·  RAMP : non
ROUNDABOUT : non
[ Copier l'ID ]
```
- Formatage FR : `Intl.NumberFormat('fr-FR')` -> séparateur d'espace fine pour milliers.
- agregId tronqué à 12 caractères + ellipse, valeur complète accessible via tooltip et bouton "Copier l'ID" (`navigator.clipboard.writeText`).
- KPI label `#6b7280` 11px, value `#0f1424` 18px bold.
- Section contexte : 12 px, `#374151`.
- Popup s'ancre sur le centre du segment cliqué, offset 12 px.

---

## 5. Fond de carte & branding

- **Tiles** : CartoDB Positron (`https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png`), attribution OSM + Carto.
- **Alternative** : CartoDB Voyager si lisibilité accrue requise (labels plus contrastés).
- **Vue initiale** : center `[4.85, 45.75]`, zoom `11`, bearing `0`, pitch `0`.
- **Bornes max** : `[[4.55, 45.55], [5.15, 45.95]]` pour cadrer la Métropole.
- **Bandeau titre** : top-center, fond translucide blanc 92 %, "Carte des volumes de trafic 2025 — Grand Lyon" 18 px semi-bold `#0f1424`.
- **Logo MDL** : top-left du panneau légende (32 px), au-dessus du toggle.
- **Top-right** : groupe contrôles MapLibre (zoom in/out, reset, plein écran).
- **Bottom-right** : sélecteur de fond (Positron / Voyager) + attribution.

---

## 6. Switch de mode TVr ↔ DPL

- Toggle dans le header du panneau légende.
- Transition couleur : `paint-property-transition` MapLibre `{duration: 300, delay: 0}` sur `line-color`.
- Réécriture des `line-width` (sans animation, instantané).
- Légende et bornes mises à jour ; titre passe à "DPL (PL) en véh/j par sens".
- Popup ouvert : on rafraîchit ses valeurs en place.
- **URL hash** : `#mode=TVr` / `#mode=DPL`, parsé au boot (`window.location.hash`) et synchronisé via `history.replaceState`.
- Raccourci clavier : `T` pour TVr, `P` pour DPL.

---

## 7. Budget de performance

| Métrique | Cible |
|---|---|
| Chargement initial (50 Mbps) | < 5 s |
| Pan / zoom | ≥ 30 FPS |
| Réponse filtre légende | < 200 ms |
| Poids total (HTML + data) | < 30 MB |

**Mesures** :
- Convertir le GeoJSON 81 MB -> **PMTiles** (vector) via `tippecanoe` : `-zg --drop-densest-as-needed -l flows -o flows.pmtiles`. Cible ~15-20 MB.
- Si PMTiles indisponible : compresser GeoJSON -> `flows.geojson.gz` (Brotli si servi via http, sinon décompression côté client via `DecompressionStream('gzip')`). Estimation ~12 MB.
- Propriétés conservées dans les tiles : `agregId, TVr, TVrmin, TVrmax, DPL, DPLmin, DPLmax, PL, PLr, FC, FUNC_CLASS, RAMP, ROUNDABOUT, n_merged, length_m`. Le reste laissé hors-tiles.
- Source MapLibre `type: 'vector'` + `protocol pmtiles://`.
- Pas de re-render complet sur toggle : on swap `line-color` paint property uniquement.

---

## 8. Accessibilité & finitions

- Contraste WCAG AA :
  - Texte légende `#cdd3df` sur `#0f1424` -> ratio 11.4:1 (AAA).
  - Note `#9aa3b2` sur `#0f1424` -> ratio 6.6:1 (AA large).
- Focus visible : outline 2 px `#22d3ee` sur swatches, toggle, boutons.
- Navigation clavier : Tab cycle ordonné (toggle -> 7 swatches -> contrôles map -> sélecteur de fond). `Enter`/`Espace` active swatch/toggle.
- ARIA : `role="region" aria-label="Légende des flux"` sur le panneau, `aria-pressed` sur swatches.
- Mobile (<768 px) :
  - Légende repliée derrière bouton ☰ flottant en bas-droite.
  - Popup en bottom-sheet plein largeur, drag pour fermer.
  - Touch target ≥ 44×44 px.
- Préfère `prefers-reduced-motion: reduce` : durée transitions ramenée à 0.

---

## Résumé final

**Fichier livré** : `scripts/map_2025_light/design_spec.md`

**Trois choix de design clés** :
- Palette 7 classes fidèle au Compass (jaune `#f7e7a1` -> brun rouge `#7a1f0f`), réutilisée à l'identique pour TVr et DPL avec bornes adaptées (10x plus bas pour DPL), assurant une lecture cohérente d'un mode à l'autre.
- Stockage en PMTiles vector pour tenir le budget < 30 MB et garder ≥ 30 FPS sur 98 k segments — fallback GeoJSON gzip seulement si l'outillage tippecanoe n'est pas disponible.
- Légende interactive (clic = filtre de classe) combinée à un toggle TVr/DPL avec transition couleur 300 ms et URL hash partageable, plutôt qu'un panneau statique.

**Question ouverte** : Faut-il que le **clic sur une classe de la légende la masque** (filtre actif, comme proposé) ou simplement l'**informe** (hover -> mise en avant des segments de cette classe sans filtrage) ? La première option est plus puissante mais peut surprendre des utilisateurs habitués à une légende statique.
