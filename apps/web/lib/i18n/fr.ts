/**
 * Centralised French strings for the marketing-facing copy that gets
 * touched the most. Not a full i18n setup — just a single source of
 * truth so design/copy iterations don't require hunting through pages.
 */
export const fr = {
  common: {
    appName: "MDL Redressement",
    appTagline: "Pipeline de modelisation FCD",
    back: "Retour",
    next: "Continuer",
    cancel: "Annuler",
    save: "Enregistrer",
    download: "Telecharger",
    upload: "Importer",
    loading: "Chargement",
    retry: "Reessayer",
    home: "Accueil",
    logout: "Deconnexion",
    yes: "Oui",
    no: "Non",
  },
  landing: {
    title: "Modelisation de redressement FCD",
    subtitle:
      "Selectionnez un mode pour commencer. Tous les calculs s'effectuent sur le serveur.",
    cards: {
      tv: { title: "Modele TV", desc: "Tous Vehicules — entrainement et evaluation" },
      pl: { title: "Modele PL", desc: "Poids Lourds — entrainement et evaluation" },
      carte: { title: "Carte de debits", desc: "Application des modeles TV+PL sur reseau" },
      compteurs: { title: "Boucles de comptage", desc: "Standardisation des fichiers" },
    },
  },
  pipeline: {
    steps: {
      donnees: "Donnees",
      config: "Configuration",
      training: "Entrainement",
      evaluation: "Evaluation",
    },
    donnees: {
      title: "Etape 1 — Donnees",
      dropzone: "Glissez votre fichier ici ou cliquez pour parcourir",
      formats: "CSV, XLSX, SHP, GeoJSON",
    },
    config: {
      title: "Etape 2 — Configuration",
      runBtn: "Lancer le grid search",
    },
    training: {
      title: "Etape 3 — Entrainement",
      runningLabel: "Entrainement en cours",
      cancel: "Annuler",
      completed: "Entrainement termine",
      failed: "Entrainement echoue",
      epoch: (cur: number, tot: number) => `Epoch ${cur} / ${tot || "?"}`,
    },
    evaluation: {
      title: "Etape 4 — Evaluation",
      runBtn: "Lancer l'evaluation",
      reportTitle: "Rapport d'evaluation",
    },
  },
  auth: {
    login: {
      title: "Connexion",
      subtitle: "Accedez au pipeline MDL Redressement",
      email: "Adresse email",
      password: "Mot de passe",
      submit: "Se connecter",
      loading: "Connexion en cours...",
      noAccount: "Pas encore de compte ?",
      register: "Creer un compte",
    },
    register: {
      title: "Creer un compte",
      subtitle: "Inscrivez-vous pour utiliser MDL Redressement",
      submit: "Creer le compte",
      loading: "Inscription en cours...",
      hasAccount: "Deja un compte ?",
      login: "Se connecter",
      passwordsMismatch: "Les mots de passe ne correspondent pas",
      passwordTooShort: "Le mot de passe doit contenir au moins 8 caracteres",
    },
  },
} as const;

export type Dict = typeof fr;
