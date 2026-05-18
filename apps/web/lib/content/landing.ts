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
    subtitle:
      "Modeles neuronaux, compteurs permanents et donnees FCD pour le redressement et la modelisation du trafic routier.",
    tagline:
      "Choisissez un outil ci-dessous. Tous les calculs s'executent cote serveur, donnees isolees par session.",
  },

  modes: [
    {
      id: "tv",
      shortTitle: "TV",
      title: "Modele Tous Vehicules",
      tagline: "Reseau neuronal calibre sur compteurs permanents et FCD apparies.",
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
      title: "Modele Poids Lourds",
      tagline: "Meme pipeline que TV, parametres et ponderations specifiques aux PL.",
      description:
        "Reutilise l'infrastructure TV avec des sample weights renforces sur les capteurs permanents (x4 par defaut) et une grille adaptee aux faibles volumes. Seed figee pour garantir la reproductibilite entre runs.",
      keyMetrics: [
        "Sample weights x4 capteurs permanents",
        "Reproductible (seed figee)",
        "Format .keras natif",
      ],
      cta: "Lancer l'analyse PL",
    },
    {
      id: "carte",
      shortTitle: "Carte",
      title: "Carte de Debits",
      tagline: "Application des modeles TV et PL sur le reseau FCD complet.",
      description:
        "Charge un modele entraine, applique les predictions segment par segment et genere un GeoJSON enrichi (TVr, DPL, intervalles de confiance). Viewer maplibre integre avec filtres dynamiques et palette graduee.",
      keyMetrics: [
        "Palette graduee 7 paliers",
        "Filtres TVr / FC",
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
  ],

  quickStats: [
    {
      label: "Modeles entraines",
      value: "127",
      hint: "Depuis le debut de l'annee",
    },
    {
      label: "Precision moyenne",
      value: "94%",
      hint: "GEH < 5 sur jeux de validation",
    },
    {
      label: "Segments traites",
      value: "48k",
      hint: "Cumul des cartes generees",
    },
    {
      label: "Sessions actives",
      value: "6",
      hint: "Ce mois-ci",
    },
  ],

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
