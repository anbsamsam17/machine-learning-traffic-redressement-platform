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
      title: "Machine Learning : Redressement FCD Tous Vehicules",
      tagline: "Reseau neuronal calibre sur FCD HERE et compteurs locaux.",
      description:
        "Pipeline complet : import des releves, mapping des features, grid search adaptatif sur l'architecture et les hyperparametres, evaluation GEH et export du modele .keras. Rapports d'erreur par classe TMJA livres en fin de run.",
      keyMetrics: [
        "GEH < 5",
        "Huber / MSE / MAE",
        "Grid search adaptatif",
      ],
      cta: "Lancer l'analyse TV",
    },
    {
      id: "pl",
      shortTitle: "PL",
      title: "Machine Learning : Redressement FCD Poids Lourds",
      tagline: "Reseau neuronal calibre sur FCD HERE et compteurs permanents PL.",
      description:
        "Pipeline complet dedie aux poids lourds : import des releves, mapping des features, grid search adaptatif sur l'architecture et les hyperparametres, sample weights renforces sur les capteurs permanents (x4 par defaut), evaluation GEH et export du modele .keras. Rapports d'erreur par classe TMJA PL livres en fin de run.",
      keyMetrics: [
        "GEH < 5",
        "Sample weights x4 capteurs permanents",
        "Grid search adaptatif",
      ],
      cta: "Lancer l'analyse PL",
    },
    {
      id: "hpm",
      shortTitle: "HPM",
      title: "Machine Learning : Redressement debit Heure de Pointe Matin",
      tagline: "Reseau neuronal calibre sur la fenetre horaire 8h-9h (v/h).",
      description:
        "Pipeline dedie a l'heure de pointe matin : entree FCD horaire 8h-9h, cible TxPen_HPM, sortie HPM_FCDr (debit redresse en vehicules par heure). Architecture identique a la chaine TV mais cible et features specifiques a la fenetre 8h-9h. Rapports d'erreur par classe de debit livres en fin de run.",
      keyMetrics: [
        "Fenetre 8h-9h",
        "Cible TxPen_HPM",
        "Sortie HPM_FCDr (v/h)",
      ],
      cta: "Lancer l'analyse HPM",
    },
    {
      id: "hps",
      shortTitle: "HPS",
      title: "Machine Learning : Redressement debit Heure de Pointe Soir",
      tagline: "Reseau neuronal calibre sur la fenetre horaire 17h-18h (v/h).",
      description:
        "Pipeline dedie a l'heure de pointe soir : entree FCD horaire 17h-18h, cible TxPen_HPS, sortie HPS_FCDr (debit redresse en vehicules par heure). Architecture identique a la chaine TV mais cible et features specifiques a la fenetre 17h-18h. Rapports d'erreur par classe de debit livres en fin de run.",
      keyMetrics: [
        "Fenetre 17h-18h",
        "Cible TxPen_HPS",
        "Sortie HPS_FCDr (v/h)",
      ],
      cta: "Lancer l'analyse HPS",
    },
    {
      id: "carte",
      shortTitle: "Carte",
      title: "Carte de Debits",
      tagline: "Application des modeles TV et PL sur le reseau FCD complet.",
      description:
        "Charge un modele entraine, applique les predictions segment par segment et genere un GeoJSON enrichi (JOr, DPL, intervalles de confiance). Viewer maplibre integre avec filtres dynamiques et palette graduee.",
      keyMetrics: [
        "Palette graduee 7 paliers",
        "Filtres JOr / FC",
        "Viewer maplibre integre",
      ],
      cta: "Ouvrir la carte",
    },
    {
      id: "compteurs",
      shortTitle: "Compteurs",
      title: "Fichier Compteurs",
      tagline: "Extraction standardisee pour partage tiers et SIG.",
      description:
        "Genere le fichier counting-loops au format standardise (9 colonnes, geometries WKT). Export GeoJSON parallele pour ouverture directe dans QGIS ou ArcGIS, sans retouche manuelle.",
      keyMetrics: [
        "Schema standardise 9 colonnes",
        "Export GeoJSON",
        "Compatible QGIS",
      ],
      cta: "Generer le fichier",
    },
    {
      id: "visualisation",
      shortTitle: "Visualisation",
      title: "Carte + Capteurs",
      tagline: "Visualisez carte de debits et points de comptage sur la meme vue.",
      description:
        "Chargez un GeoJSON de predictions (sortie module Carte) et un fichier capteurs (CSV/xlsx) pour une vue interactive complete : segments colories, capteurs TV/PL, popups detailles, lien Street View et filtres dynamiques.",
      keyMetrics: [
        "Lignes + Points",
        "Popups detailles",
        "Street View",
      ],
      cta: "Ouvrir",
    },
    {
      id: "discontinuites",
      shortTitle: "Discontinuites",
      title: "Analyse des discontinuites JOr",
      tagline: "Detecte les sauts de debit entre arcs adjacents et explique les causes.",
      description:
        "Charge un GeoJSON enrichi (JOr/DPL par segment), execute le pipeline de detection cote serveur (5 etapes, 30 s - 2 min selon volume) puis affiche une carte interactive des noeuds discontinus avec cause principale, topologie, drivers rankes et table par segment.",
      keyMetrics: [
        "8 causes typees",
        "3 topologies",
        "Popups drill-down",
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
