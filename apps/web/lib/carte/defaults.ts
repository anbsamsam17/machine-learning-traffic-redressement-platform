// ---------------------------------------------------------------------------
// Carte — Defaults & constantes (extraits de app/carte/page.tsx)
// ---------------------------------------------------------------------------
// Toutes les valeurs sont calibrees pour Grand Lyon (cf SATURATION_*_specs.md).
// Ne pas modifier sans mettre a jour la doc + tests de regression.
// ---------------------------------------------------------------------------

// --- PL saturation (v2 hybride adaptative — SATURATION_PL_specs.md) ---

// Cap absolu PL/jour par classe fonctionnelle HERE (BORNES_FC_ABS)
export const PL_SAT_BORNES_DEFAULTS = {
  fc1: 15000,
  fc2: 5000,
  fc3: 3000,
  fc4: 1500,
  fc5: 800,
} as const;

// Plancher du ratio PL/JOr par classe fonctionnelle HERE (ALPHA_FC_MIN), saisi en %
export const PL_SAT_ALPHA_DEFAULTS = {
  fc1: 35,
  fc2: 25,
  fc3: 18,
  fc4: 15,
  fc5: 12,
} as const;

// Hyperparamètres v2 hybride adaptative
// - RATIO_MACRO_PEN : 1.137 = mean(TxPenTV) / mean(TxPenPL) sur 991 capteurs Lyon 2025
// - ALPHA_PHYSIQUE_MAX : 55 % = plafond biomécanique CEREMA (au-delà = aberration)
// - SEUIL_VOL_FCD_TV : 50 véh/j = sous ce seuil le ratio FCD est bruité, fallback plancher
export const PL_SAT_V2_DEFAULTS = {
  ratioMacroPen: 1.137,
  alphaPhysiqueMax: 55, // saisi en %, envoyé /100 dans payload
  seuilVolFcdTv: 50,
} as const;

// --- v3 zones critiques (override capteurs SIREDO PL) ---
export const PL_SAT_V3_DEFAULTS = {
  zoneCritEnabled: true,
  anneeCapteurs: 2025,
  ratioCapteurCritique: 15, // saisi en %
  bufferZoneCritiqueM: 1000,
  alphaMinZoneCritique: 30, // saisi en %
} as const;

// --- Libelles FC partages dans toutes les sections ---
export const FC_LABELS: { key: 1 | 2 | 3 | 4 | 5; label: string; type: string }[] = [
  { key: 1, label: "FC1", type: "Autoroute" },
  { key: 2, label: "FC2", type: "Voie rapide" },
  { key: 3, label: "FC3", type: "Axe urbain" },
  { key: 4, label: "FC4", type: "Rue principale" },
  { key: 5, label: "FC5", type: "Rue locale" },
];

// --- HPM saturation (SATURATION_HPM_HPS_specs.md — 991 capteurs SIREDO Lyon 2025) ---

// Cap dur PM (val/h) par classe fonctionnelle HERE
export const HPM_SAT_BORNES_DEFAULTS = {
  fc1: 5000,
  fc2: 7000,
  fc3: 4000,
  fc4: 1500,
  fc5: 700,
} as const;

// Ratio max PM/JOr par classe fonctionnelle HERE (saisi en %)
export const HPM_SAT_ALPHA_DEFAULTS = {
  fc1: 10,
  fc2: 18,
  fc3: 16,
  fc4: 18,
  fc5: 18,
} as const;

// --- HPS saturation ---

// Cap dur PS (val/h) par classe fonctionnelle HERE
export const HPS_SAT_BORNES_DEFAULTS = {
  fc1: 5000,
  fc2: 7000,
  fc3: 4000,
  fc4: 1500,
  fc5: 800,
} as const;

// Ratio max PS/JOr par classe fonctionnelle HERE (saisi en %)
export const HPS_SAT_ALPHA_DEFAULTS = {
  fc1: 12,
  fc2: 15,
  fc3: 15,
  fc4: 20,
  fc5: 15,
} as const;
