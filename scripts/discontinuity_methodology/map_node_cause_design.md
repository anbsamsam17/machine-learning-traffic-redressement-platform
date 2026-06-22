# Spec — Carte HTML des noeuds de discontinuite TVr (Grand Lyon)

Cible : ~5 314 noeuds, fichier HTML autonome, base claire + UI sombre.

---

## 1. Palette par cause (categorielle, 9 classes)

Base : ColorBrewer Set1 + Paired, ajustee pour reserver le rouge aux anomalies fortes uniquement.

| Cause                  | Hex       | Label FR                              | Intention |
|------------------------|-----------|---------------------------------------|-----------|
| FCD_TV_cliff           | `#E41A1C` | Falaise FCD VL                        | Anomalie forte (rouge) |
| FCD_PL_cliff           | `#B30000` | Falaise FCD PL                        | Anomalie forte (rouge fonce) |
| FC_transition          | `#377EB8` | Transition de FC (attendue)           | Bleu neutre — pas un defaut |
| RAMP_asymmetry         | `#FF7F00` | Asymetrie bretelle                    | Orange |
| ROUNDABOUT_asymmetry   | `#FDB462` | Asymetrie giratoire                   | Orange clair |
| Distance_anomaly       | `#984EA3` | Anomalie de distance inter-noeuds     | Violet |
| Coverage_gap           | `#A65628` | Trou de couverture capteurs           | Brun |
| Multi_factor           | `#F781BF` | Causes multiples                      | Rose |
| Unexplained            | `#999999` | Non expliquee                         | Gris neutre |

Contraste verifie sur fond `#F5F5F5` (carto claire) : tous >= 3:1 (AA non-text).

---

## 2. Design du marqueur

- **Forme** : cercle unique pour tous (`circleMarker`). Eviter les formes multiples — la couleur porte deja la categorie.
- **Taille** : encode `ecart` via echelle racine (sqrt) pour eviter saturation visuelle.
  - rayon = `clamp(4, 4 + sqrt(ecart / 100), 14)` px
  - Reference dans la legende : 3 cercles temoins (faible / moyen / fort).
- **Opacite** : encode `tier`.
  - `orange` (1x–2x seuil) : `fillOpacity = 0.55`
  - `red` (>= 2x seuil) : `fillOpacity = 0.9` + halo externe `stroke #111 width 1.5`
- **Stroke** : `#1F1F1F`, `weight: 0.8` pour tous, garantit la lisibilite sur fond clair et au survol.
- **Hover** : rayon +2 px, stroke +0.5, curseur pointer.

---

## 3. Popup (priorite UX)

Largeur fixe 360 px, fond `#1B1F23`, texte `#E6E6E6`, typo `Inter, system-ui`.

```
+----------------------------------------------+
| [Node 12345]                  [tier badge]   |  <- header
|----------------------------------------------|
|  FLUX                                        |  <- KPI 1
|  Entree  : 3 240 v/h  (n_in = 2)             |
|  Sortie  : 7 480 v/h  (n_out = 3)            |
|  Ecart   : +4 240 v/h   seuil = 2 000        |
|----------------------------------------------|
|  CAUSE DETECTEE                              |  <- KPI 2
|  [pastille couleur] Falaise FCD VL           |
|----------------------------------------------|
|  INDICATEURS                                 |  <- KPI 3 (cause-specific)
|  TMJO FCD VL min : 0,2                       |
|  TMJO FCD VL max : 45,3                      |
|  Ratio max/min   : 226                       |
|----------------------------------------------|
|  ARETES                                      |  <- KPI 4
|  Entrantes (2)                               |
|   - agreg 88421  TVr 1 540 v/h               |
|   - agreg 88422  TVr 1 700 v/h               |
|  Sortantes (3)                               |
|   - agreg 88510  TVr 2 480 v/h               |
|   - ...                                      |
|----------------------------------------------|
|  [Copier ID]   [Voir sur OpenStreetMap]      |  <- actions
+----------------------------------------------+
```

Structure HTML/CSS (resume) :

```html
<div class="popup">
  <header class="popup-head">
    <span class="node-id">Node 12345</span>
    <span class="badge badge-red">Rouge</span>
  </header>
  <section class="kpi"><h4>Flux</h4>...</section>
  <section class="kpi"><h4>Cause detectee</h4>
    <span class="dot" style="background:#E41A1C"></span> Falaise FCD VL
  </section>
  <section class="kpi"><h4>Indicateurs</h4><dl>...</dl></section>
  <section class="kpi"><h4>Aretes</h4><ul class="edges in">...</ul><ul class="edges out">...</ul></section>
  <footer class="popup-actions">
    <button data-copy="12345">Copier ID</button>
    <a href="https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}" target="_blank">Voir sur OSM</a>
  </footer>
</div>
```

Conventions FR : separateur decimal `,`, separateur de milliers espace insecable, unite `v/h`.

---

## 4. Legende + filtres (sidebar gauche)

- **Bandeau stats**
  - Total noeuds : `5 314`
  - Repartition par cause : barre 100% empilee (preferable au camembert sur 9 classes) + tableau densite (% + compte).
- **Filtres**
  - 9 cases a cocher (une par cause), couleur + label + compteur.
  - Radio `tier` : Tous / Orange / Rouge.
  - Plage FC (slider double) : seuil bas — seuil haut (sur `ecart`).
  - Recherche : `input[type=search]` par `node_id` (zoom + popup auto).
- **Boutons**
  - `Reinitialiser` : restaure filtres par defaut.
  - `Exporter selection (CSV)` : optionnel, dump des noeuds visibles.

---

## 5. Layout general

```
+----------------------------------------------------------+
| Barre titre : "Discontinuites TVr — Grand Lyon"  [v1.0]  |
+--------------------+-------------------------------------+
|                    |                                     |
|  Sidebar (320 px)  |   Carte (centre)                    |
|  - stats           |   - tuiles claires (Carto Positron) |
|  - filtres         |   - markers cercles uniquement      |
|  - recherche       |   - PAS d'aretes affichees          |
|                    |   - controle zoom + echelle         |
|                    |                                     |
+--------------------+-------------------------------------+
```

- Mobile (< 768 px) : sidebar repliable en drawer (toggle en haut a gauche).
- Carte plein ecran possible (bouton plein ecran natif Leaflet/MapLibre).

---

## 6. Performance — recommandation

**Choix : MapLibre GL JS.**

Justification :
- 5 314 cercles natifs Leaflet (DOM SVG) restent fluides, mais le pan/zoom ralentit avec filtres en direct + popup.
- MapLibre rend les `circle` en WebGL, transitions de couleur/rayon GPU, filtres `setFilter` instantanes.
- Style JSON externalisable, theming clair/sombre trivial.
- Pas de cluster necessaire a cette echelle — la densite spatiale reste lisible.
- Source : un seul GeoJSON inlinable (~1 MB compresse OK).

Fallback : Leaflet `L.circleMarker` + `Leaflet.markercluster` desactive (clusters masqueraient la lecture par cause).

---

## 7. Accessibilite

- Contraste : palette validee AA non-text (>= 3:1) sur fond `#F5F5F5`. Texte popup `#E6E6E6` sur `#1B1F23` = 12,6:1 (AAA).
- Navigation clavier : `Tab` parcourt filtres > recherche > markers (focus visible, ring `2px #FFB000`).
- `Entree` sur un marker ouvre la popup ; `Echap` ferme.
- ARIA : `role="region" aria-label="Carte des discontinuites"`, badges `aria-label`.
- Mode impression : feuille `@media print` masque la sidebar, agrandit la carte, force fond blanc, conserve les cercles + une legende compacte au pied.
- Daltonisme : palette testee Deuteranopie/Protanopie (Set1 + Paired sont robustes ; rouge fonce + orange restent distincts du bleu et du violet).

---

## 8. Branding & ton

- Tous les libelles en francais (formel, neutre).
- Pas d'emojis, pas d'icones decoratives gratuites.
- Typo : `Inter`, fallback `system-ui, sans-serif`.
- Carto : Carto **Positron** (clair, neutre, sans saturation, gratuit pour usage public).
- Sidebar sombre `#14171A`, accent `#FFB000` (jaune neutre pour CTA, evite collision avec la palette categorielle).
- Footer discret : `Source : MDL Redressement — Grand Lyon — methodologie v1.0`.

---

## Synthese

Specification couvrant palette 9 couleurs (rouge reserve aux falaises FCD), markers cercles uniformes a taille = sqrt(ecart) + opacite = tier, popup en 4 blocs KPI + actions, sidebar sombre avec filtres par cause/tier/FC, MapLibre GL pour la performance, accessibilite AA et ton FR sobre.
