# Changelog

Tous les changements notables de ce projet sont consignés dans ce fichier.

Le format s'inspire de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/),
et le projet suit une approche de versionnement par jalons.

## [Unreleased]

Jalons majeurs livrés, regroupés par thème (sans dates précises).

### Added

- **Moteur ML de redressement par MLP quantile** : architecture MLP paramétrable
  (`neurons_factors`), tête multi-quantile (q ∈ {0.2, 0.5, 0.8}), pertes métier
  custom (pinball, tolerance-aware, huber) persistées avec le modèle.
- **Évaluation statistique sous contrainte métier** : intervalles de confiance 95 %
  par bootstrap (1000 rééchantillonnages, seed 1750), test de **McNemar apparié**
  (verdict directionnel), drift temporel année par année, stratification par volume
  de trafic.
- **Analyse des discontinuités du réseau** : reconstruction de graphe orienté depuis
  le schéma HERE, conservation des flux aux nœuds (GEH), classification automatique
  des causes.
- **Carte d'évolution inter-années** : matching géospatial à 3 niveaux (clé exacte,
  map-matching géométrique EPSG:2154 + affectation hongroise, vérification BAN),
  viewer COMPASS, rendu carte fix.
- **Carte des débits redressés** : popups JOr/DPL/PM/PS avec intervalles de
  confiance, auto-mapping FCDREFGLOBAL, rendu MapLibre LineLayer unique.
- **Traçabilité ML / lineage** : `meta.json` (versions d'environnement, git SHA,
  seed, SHA-256 des données), reproductibilité bit-exact (seed 1750).

### Changed

- **Durcissement sécurité** : JWT fail-fast au boot, anti-IDOR (404 vs 403),
  anti path-traversal, anti zip-bomb (limite 1 Go), headers OWASP, durcissement
  production (`/docs` désactivés, `/metrics` restreint, CORS strict).
- **CI multi-arch** : lint (`ruff` + `black`) + `eslint` + `pytest` (service Redis),
  build d'images Docker **multi-arch (amd64/arm64)** poussées sur GHCR, déploiement
  SSH avec approbation manuelle.

### Fixed

- Modèle PL rendu optionnel et mapping d'année robuste (casse, float/int).
- Carte d'évolution : correction du rendu, matching clé + géo + BAN.
- Login : correction du dépassement de pile sur les particules de fond animé.
