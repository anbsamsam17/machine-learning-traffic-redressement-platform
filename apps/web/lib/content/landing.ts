/**
 * Landing page copy — MDL Redressement
 * Public surface for the post-login home screen and Sam mascot mood messages.
 *
 * Convention projet :
 *   - Francais sans accents (coherence avec le reste de l'app)
 *   - Pas d'emoji
 *   - Ton ingenieur : sobre, technique, sans marketing-speak
 */

export const landingContent = {
  hero: {
    eyebrow: "Plateforme interne · v2.0",
    title: "Outils Data Engineering · Etudes Trafic",
    subtitle: "",
    tagline:
      "Choisissez un outil ci-dessous. Tous les calculs s'executent cote serveur, donnees isolees par session.",
  },

  modes: [
    {
      id: "tv",
      shortTitle: "TV",
      title: "Redressement FCD Tous Vehicules",
      tagline:
        "Reseau de neurones calibre sur traces FCD HERE et compteurs terrain.",
      description:
        "Pipeline TensorFlow/Keras qui apprend le taux de penetration TxPen a partir de 7 features HERE : debits FCD VL/PL, distances moyennes, vitesses, classe fonctionnelle one-hot. Grid search combinatoire sur l'architecture, l'optimiseur (Adam, AdamW), le schedule de dropout, la couche de normalisation (BatchNorm, LayerNorm) et la loss (Huber 0.25, MSE, MAE, pinball quantile). Hard example mining et curriculum learning activables par config. EarlyStopping sur val_loss, ReduceLROnPlateau, multi-seed avec op determinism TF pour la reproductibilite bit-a-bit.",
      keyMetrics: [
        "GEH < 5 + bootstrap CI95 sur tol_in_pct, p80, R2",
        "Grid feature-subset + 11 axes hyperparams",
        "Sample weights x4 + quantile head q={0.2,0.5,0.8}",
      ],
      cta: "Lancer l'analyse TV",
    },
    {
      id: "pl",
      shortTitle: "PL",
      title: "Redressement FCD Poids Lourds",
      tagline:
        "Variante PL calibree sur capteurs permanents Siredo, sample weights renforces.",
      description:
        "Pipeline derive de la chaine TV pour la cible TxPenPL, avec 9 features dont 3 derivees en amont : fcd_log, tv_pl_ratio, dist_to_lyon_center. La recipe Compact4 figee apres grid search tourne sur 5 couches denses, batch 64, 1500 epochs, dropout 0.015. Sample weights x4 sur les capteurs permanents Siredo et boost x2 sur l'annee la plus recente (auto-detection MAX year_mapped). Stratification GEH par classe TMJA, metriques bootstrappees CI95, rapport HTML PL dedie avec carte folium.",
      keyMetrics: [
        "R2 0.97, MAE 0.17, GEH < 5 a 99.86% (700 capteurs Grand Lyon)",
        "Sample weights x4 capteurs permanents + x2 annee recente",
        "Features derivees fcd_log, tv_pl_ratio, dist_to_lyon_center",
      ],
      cta: "Lancer l'analyse PL",
    },
    {
      id: "hpm",
      shortTitle: "HPM",
      title: "Redressement debit Heure de Pointe Matin",
      tagline:
        "Reseau de neurones cible sur la fenetre 8h-9h, sortie en v/h.",
      description:
        "Specialisation horaire de la chaine TV sur la fenetre h08 (8h00-8h59, convention CEREMA Grand Lyon). La cible TxPen_HPM se derive de FCD_HPM_TV sur TMJOBCTV_HPM, la sortie HPM_FCDr donne le debit redresse en vehicules/heure. Architecture, callbacks et grid identiques au pipeline TV, features et target retravaillees pour la pointe matin. Evaluation GEH/MAE/R2 stratifiee par debit horaire et generateur de rapport peak dedie.",
      keyMetrics: [
        "Fenetre h08-h09 (CEREMA Grand Lyon)",
        "Cible TxPen_HPM, sortie HPM_FCDr en v/h",
        "GEH horaire stratifie + rapport HTML peak dedie",
      ],
      cta: "Lancer l'analyse HPM",
    },
    {
      id: "hps",
      shortTitle: "HPS",
      title: "Redressement debit Heure de Pointe Soir",
      tagline:
        "Reseau de neurones cible sur la fenetre 17h-18h, sortie en v/h.",
      description:
        "Pendant soir de HPM, sur la fenetre h17 (17h00-17h59). La cible TxPen_HPS se derive de FCD_HPS_TV sur TMJOBCTV_HPS, la sortie HPS_FCDr donne le debit redresse en vehicules/heure. La chaine reutilise l'architecture, les callbacks et la grille TV, avec features et target propres au pic du soir. Rapport HTML peak et carte folium specifiques a la fenetre horaire.",
      keyMetrics: [
        "Fenetre h17-h18 (CEREMA Grand Lyon)",
        "Cible TxPen_HPS, sortie HPS_FCDr en v/h",
        "GEH horaire stratifie + rapport HTML peak dedie",
      ],
      cta: "Lancer l'analyse HPS",
    },
    {
      id: "carte",
      shortTitle: "Carte",
      title: "Carte de Debits",
      tagline:
        "Inference cartographique TV+PL+HPM+HPS sur reseau FCD, sortie GeoJSON exploitable.",
      description:
        "Charge un modele Keras entraine, normalise les features FCD (HERE/SIREDO) et applique les predictions segment par segment. Post-traitement metier : saturation hierarchique v3 PL (ratio FCD adaptatif, plancher par classe fonctionnelle HERE FC1-FC5, plafond biomecanique CEREMA 0.55), override zones critiques (buffer 1 km en Lambert-93 EPSG:2154 autour des capteurs SIREDO depassant 15% de ratio PL/TV), arrondi progressif 3 paliers (multiples de 5, 10, 100 selon l'ordre de grandeur). Sortie GeoJSON enrichie (JOr, DPL, PM, PS, intervalles de confiance) servie inline pour le viewer MapLibre GL JS integre.",
      keyMetrics: [
        "Saturation v3 + override SIREDO 1 km EPSG:2154",
        "Arrondi progressif 3 paliers post-IC",
        "4 modeles combines (TV, PL, HPM, HPS)",
      ],
      cta: "Generer la carte",
    },
    {
      id: "compteurs",
      shortTitle: "Compteurs",
      title: "Fichier Compteurs",
      tagline:
        "Extraction standardisee des boucles de comptage pour partage SIG tiers.",
      description:
        "Genere le fichier counting-loops au schema canonique 9 colonnes (Identifiant Poste/Section, Annee, Commune, RD, PRD, Type capteur, TMJA TV, TMJA PL, Sens de comptage). Coercion numerique tolerante aux decimales francaises, normalisation des aliases lat/lon (10 variantes detectees), dispatch par format CSV / xlsx / Parquet / GeoJSON. Sortie GeoJSON Point en WGS84 (EPSG:4326), exploitable directement dans QGIS ou ArcGIS sans retouche manuelle, avec stats de distribution par annee et par type de capteur.",
      keyMetrics: [
        "Schema canonique 9 colonnes, WGS84",
        "4 formats acceptes en entree",
        "Export QGIS / ArcGIS sans retouche",
      ],
      cta: "Generer le fichier",
    },
    {
      id: "visualisation",
      shortTitle: "Visualisation",
      title: "Carte + Capteurs",
      tagline:
        "Vue interactive segments redresses et points de comptage sur une seule carte.",
      description:
        "Maille un GeoJSON de segments (LineString JOr / DPL / PM / PS) et un fichier capteurs (CSV, xlsx, Parquet ou GeoJSON Point) dans un viewer MapLibre GL JS unique. Rendu trois couches halo + core + shine pour l'effet neon lisible sur fond satellite ou Carto Dark Matter, palette TVr graduee chaude (7 paliers) et DPL froide (8 paliers), filtres dynamiques, popups detailles, lien Street View et bbox auto-zoom. Backend FastAPI : validation defensive (agregId + au moins une colonne de debit JOr ou TVr legacy), support multi-format avec sidecar metadata cache pour les GET.",
      keyMetrics: [
        "3 couches MapLibre halo / core / shine",
        "Palettes TVr 7 paliers + DPL 8 paliers",
        "Multi-format : CSV / xlsx / Parquet / GeoJSON",
      ],
      cta: "Ouvrir la vue",
    },
    {
      id: "discontinuites",
      shortTitle: "Discontinuites",
      title: "Analyse des discontinuites JOr",
      tagline:
        "Detection algorithmique des ruptures de flux entre arcs HERE adjacents.",
      description:
        "Reconstruit le graphe oriente HERE depuis les suffixes -F / -T des AgregId, agrege flow_in / flow_out par noeud et applique la regle utilisateur adaptative (seuil 2000 v/j si max(flow) <= 20000, sinon 4000 v/j, avec tier rouge a 2x seuil). Le scoring identifie les drivers FCD (TMJOFCDTV, TMJOFCDPL, functional_class, distances avant / minimales) puis classe chaque noeud en 8 causes typees (FCD_TV_cliff, FCD_PL_cliff, FC_transition, RAMP_asymmetry, ROUNDABOUT_asymmetry, Coverage_gap, Distance_anomaly, Unexplained) et 3 topologies (Bretelle, Carrefour, Continuite). Sortie Point FeatureCollection cartographiee dans MapLibre avec NodePanel drill-down et cross-tab cause x topologie ; jointure parquet FCDREFGLOBAL optionnelle pour completer les drivers manquants.",
      keyMetrics: [
        "8 causes typees, 3 topologies, 2 tiers de severite",
        "Pipeline 5 etapes (30s a 2 min selon volume)",
        "Jointure parquet FCDREFGLOBAL en option",
      ],
      cta: "Lancer l'analyse",
    },
  ],

  // Vide tant qu'aucun endpoint d'agregation reel n'existe (cf. apps/api/app/routers/models.py).
  // Plutot que des chiffres arbitraires, on masque le bandeau.
  quickStats: [] as ReadonlyArray<{ label: string; value: string; hint?: string }>,

  recentActivity: [
    {
      kind: "training",
      title: "Entrainement TV — autoroute A20 termine",
      time: "il y a 2h",
      status: "success",
    },
    {
      kind: "carte",
      title: "Carte de debits zone Toulouse Nord generee",
      time: "il y a 5h",
      status: "success",
    },
    {
      kind: "eval",
      title: "Eval modele PL — capteurs Eurosud",
      time: "en cours",
      status: "pending",
    },
    {
      kind: "compteurs",
      title: "Upload donnees brutes — juin 2026",
      time: "hier",
      status: "success",
    },
  ],

  sam: {
    name: "Sam",
    role: "Data Full-Stack Engineer",
    welcomeBubble: "Salut, content de te revoir !",
    welcomeSubtitle: "Pret a former de bons modeles aujourd'hui ?",
    moodMessages: {
      welcome: "Salut, content de te revoir ! On attaque par quel outil ?",
      based: "Je veille au grain. Pret quand tu l'es.",
      analysing: "Je lis tes donnees... ca prend quelques secondes.",
      thinking: "On itere sur le grid search. Patience, c'est bientot fini.",
      goodjob: "Beau modele ! GEH dans les clous, t'es bon pour livrer.",
      error: "Aie, j'ai rate quelque chose. Jette un oeil a la console ?",
    },
  },

  footer: {
    legal: "© 2026 · Usage interne · Aucune donnee diffusee a l'exterieur",
    helpLink: {
      label: "Documentation interne",
      href: "/docs",
    },
  },
} as const;

export type LandingContent = typeof landingContent;
export type ModeId = (typeof landingContent.modes)[number]["id"];
export type ActivityStatus = (typeof landingContent.recentActivity)[number]["status"];
export type ActivityKind = (typeof landingContent.recentActivity)[number]["kind"];
export type SamMood = keyof typeof landingContent.sam.moodMessages;
