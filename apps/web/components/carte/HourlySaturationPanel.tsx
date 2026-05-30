"use client";

import { motion } from "framer-motion";
import { Info, RotateCcw, Sunrise, Sunset } from "lucide-react";
import {
  FC_LABELS,
  HPM_SAT_ALPHA_DEFAULTS,
  HPM_SAT_BORNES_DEFAULTS,
  HPS_SAT_ALPHA_DEFAULTS,
  HPS_SAT_BORNES_DEFAULTS,
} from "@/lib/carte/defaults";

// ---------------------------------------------------------------------------
// HourlySaturationPanel — generique HPM / HPS
// ---------------------------------------------------------------------------
// Elimine la duplication 2x500 lignes du fichier original. Mode = "hpm" |
// "hps" pilote les libelles, les couleurs (pink vs violet), les defaults et
// le commentaire affiche dans le panel.
// ---------------------------------------------------------------------------

export type HourlyMode = "hpm" | "hps";

interface ThemeConfig {
  label: string; // "HPM" | "HPS"
  abbrev: string; // "PM" | "PS"
  iconColor: string;
  textBase: string;
  textStrong: string;
  textWeak: string;
  badgeBg: string;
  badgeBorder: string;
  badgeText: string;
  toggleBg: string;
  toggleShadow: string;
  toggleRing: string;
  toggleStrong: string;
  noticeBg: string;
  noticeBorder: string;
  noticeText: string;
  cardBg: string;
  cardBorder: string;
  cardText: string;
  cardDot: string;
  cardFocus: string;
  resetBorder: string;
  resetBorderHover: string;
  resetBg: string;
  resetBgHover: string;
  resetText: string;
  resetTextHover: string;
  iconNode: React.ReactNode;
  descriptionNode: React.ReactNode;
  bornesDefaults: { fc1: number; fc2: number; fc3: number; fc4: number; fc5: number };
  alphaDefaults: { fc1: number; fc2: number; fc3: number; fc4: number; fc5: number };
}

function getTheme(mode: HourlyMode): ThemeConfig {
  if (mode === "hpm") {
    return {
      label: "HPM",
      abbrev: "PM",
      iconColor: "text-pink-400",
      textBase: "text-pink-400",
      textStrong: "text-pink-300",
      textWeak: "text-pink-400/90",
      badgeBg: "bg-pink-500/10",
      badgeBorder: "border-pink-500/30",
      badgeText: "text-pink-300",
      toggleBg: "bg-pink-500/70",
      toggleShadow: "shadow-[0_0_8px_rgba(244,114,182,0.4)]",
      toggleRing: "focus:ring-pink-400/50",
      toggleStrong: "text-pink-300",
      noticeBg: "bg-pink-500/5",
      noticeBorder: "border-pink-500/20",
      noticeText: "text-pink-300/80",
      cardBg: "bg-pink-500/5",
      cardBorder: "border-pink-500/30",
      cardText: "text-pink-300",
      cardDot: "bg-pink-400",
      cardFocus: "focus:border-pink-400/50",
      resetBorder: "border-pink-500/30",
      resetBorderHover: "hover:border-pink-400/60",
      resetBg: "bg-pink-500/5",
      resetBgHover: "hover:bg-pink-500/10",
      resetText: "text-pink-300/90",
      resetTextHover: "hover:text-pink-200",
      iconNode: <Sunrise size={14} className="text-pink-400" />,
      descriptionNode: (
        <>
          Le modele HPM peut predire des ratios PM/journee physiquement
          aberrants (&gt;30&nbsp;% impossible). Cette saturation post-prediction
          borne PM par typologie de voie (cap absolu val/h) ET par ratio
          maximum PM/JOr. Valeurs par defaut calibrees sur 991 capteurs SIREDO
          Grand Lyon 2025.
        </>
      ),
      bornesDefaults: HPM_SAT_BORNES_DEFAULTS,
      alphaDefaults: HPM_SAT_ALPHA_DEFAULTS,
    };
  }
  // hps
  return {
    label: "HPS",
    abbrev: "PS",
    iconColor: "text-violet-400",
    textBase: "text-violet-400",
    textStrong: "text-violet-300",
    textWeak: "text-violet-400/90",
    badgeBg: "bg-violet-500/10",
    badgeBorder: "border-violet-500/30",
    badgeText: "text-violet-300",
    toggleBg: "bg-violet-500/70",
    toggleShadow: "shadow-[0_0_8px_rgba(167,139,250,0.4)]",
    toggleRing: "focus:ring-violet-400/50",
    toggleStrong: "text-violet-300",
    noticeBg: "bg-violet-500/5",
    noticeBorder: "border-violet-500/20",
    noticeText: "text-violet-300/80",
    cardBg: "bg-violet-500/5",
    cardBorder: "border-violet-500/30",
    cardText: "text-violet-300",
    cardDot: "bg-violet-400",
    cardFocus: "focus:border-violet-400/50",
    resetBorder: "border-violet-500/30",
    resetBorderHover: "hover:border-violet-400/60",
    resetBg: "bg-violet-500/5",
    resetBgHover: "hover:bg-violet-500/10",
    resetText: "text-violet-300/90",
    resetTextHover: "hover:text-violet-200",
    iconNode: <Sunset size={14} className="text-violet-400" />,
    descriptionNode: (
      <>
        Idem pour la pointe soir (17h-18h)&nbsp;: le modele HPS peut sur-predire
        les retours soir. Bornes specifiques HPS calibrees sur capteurs Lyon
        (max observe 19.73&nbsp;% PS/JOr sur FC4 rue principale &rarr;{" "}
        <span className="font-mono text-violet-400/90">
          ALPHA_HPS_FC4 = 0.20
        </span>
        ).
      </>
    ),
    bornesDefaults: HPS_SAT_BORNES_DEFAULTS,
    alphaDefaults: HPS_SAT_ALPHA_DEFAULTS,
  };
}

function sanitizePositive(raw: string, max: number): number {
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.min(n, max);
}

export interface HourlySaturationPanelProps {
  mode: HourlyMode;
  visible: boolean; // wrap dans <AnimatePresence> par le parent
  enabled: boolean;
  modified: boolean;
  onEnabledChange: (v: boolean) => void;
  borneFc1: number;
  borneFc2: number;
  borneFc3: number;
  borneFc4: number;
  borneFc5: number;
  onBorneFc1Change: (v: number) => void;
  onBorneFc2Change: (v: number) => void;
  onBorneFc3Change: (v: number) => void;
  onBorneFc4Change: (v: number) => void;
  onBorneFc5Change: (v: number) => void;
  alphaFc1: number;
  alphaFc2: number;
  alphaFc3: number;
  alphaFc4: number;
  alphaFc5: number;
  onAlphaFc1Change: (v: number) => void;
  onAlphaFc2Change: (v: number) => void;
  onAlphaFc3Change: (v: number) => void;
  onAlphaFc4Change: (v: number) => void;
  onAlphaFc5Change: (v: number) => void;
  onReset: () => void;
}

export function HourlySaturationPanel(props: HourlySaturationPanelProps) {
  const { mode, visible, enabled, modified, onEnabledChange, onReset } = props;
  if (!visible) return null;
  const t = getTheme(mode);

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="mt-8 pt-6 border-t border-white/[0.06]"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          {t.iconNode}
          <span className="text-xs font-medium text-slate-200">
            Saturation hierarchique {t.label}
          </span>
          {modified && enabled && (
            <span
              className={`text-[10px] ${t.badgeText} ${t.badgeBg} border ${t.badgeBorder} px-1.5 py-0.5 rounded`}
              title="Au moins une valeur a ete modifiee par rapport aux defaults Lyon"
            >
              modifie
            </span>
          )}
        </div>

        {/* Toggle ON/OFF */}
        <label className="flex items-center gap-2 cursor-pointer group flex-shrink-0">
          <span
            className={`text-[11px] font-medium transition-colors ${
              enabled ? t.toggleStrong : "text-slate-500"
            }`}
          >
            {enabled ? "Activee" : "Desactivee"}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            onClick={() => onEnabledChange(!enabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 ${t.toggleRing} ${
              enabled ? `${t.toggleBg} ${t.toggleShadow}` : "bg-slate-700"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                enabled ? "translate-x-5" : "translate-x-1"
              }`}
            />
          </button>
        </label>
      </div>

      <p className="text-[11px] text-slate-400 leading-relaxed mb-4">
        {t.descriptionNode}
      </p>

      {!enabled && (
        <div
          className={`mb-4 flex items-start gap-2 px-3 py-2 rounded-lg ${t.noticeBg} border ${t.noticeBorder} ${t.noticeText} text-[11px]`}
        >
          <Info size={12} className="mt-0.5 flex-shrink-0" />
          <span>
            La saturation {t.label} est desactivee. Les valeurs {t.abbrev}{" "}
            brutes du modele seront conservees (aberrations possibles).
          </span>
        </div>
      )}

      <div
        className={`space-y-6 transition-opacity ${
          enabled ? "opacity-100" : "opacity-50 pointer-events-none"
        }`}
        aria-disabled={!enabled}
      >
        {/* Sous-bloc 1 : BORNE_FC */}
        <BorneBlock
          mode={mode}
          theme={t}
          enabled={enabled}
          values={[
            props.borneFc1,
            props.borneFc2,
            props.borneFc3,
            props.borneFc4,
            props.borneFc5,
          ]}
          setters={[
            props.onBorneFc1Change,
            props.onBorneFc2Change,
            props.onBorneFc3Change,
            props.onBorneFc4Change,
            props.onBorneFc5Change,
          ]}
        />

        {/* Sous-bloc 2 : ALPHA_FC */}
        <AlphaBlock
          mode={mode}
          theme={t}
          enabled={enabled}
          values={[
            props.alphaFc1,
            props.alphaFc2,
            props.alphaFc3,
            props.alphaFc4,
            props.alphaFc5,
          ]}
          setters={[
            props.onAlphaFc1Change,
            props.onAlphaFc2Change,
            props.onAlphaFc3Change,
            props.onAlphaFc4Change,
            props.onAlphaFc5Change,
          ]}
        />

        {/* Reset button */}
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onReset}
            disabled={!enabled || !modified}
            className={`flex items-center gap-1.5 text-[10px] font-medium ${t.resetText} ${t.resetTextHover} disabled:text-slate-600 disabled:cursor-not-allowed px-2.5 py-1.5 rounded-md border ${t.resetBorder} ${t.resetBorderHover} disabled:border-white/[0.05] ${t.resetBg} ${t.resetBgHover} disabled:bg-transparent transition-colors`}
            title="Restaurer les valeurs par defaut calibrees Grand Lyon"
          >
            <RotateCcw size={11} />
            <span>Reinitialiser aux valeurs Lyon</span>
          </button>
        </div>
      </div>
    </motion.div>
  );
}

interface BlockProps {
  mode: HourlyMode;
  theme: ThemeConfig;
  enabled: boolean;
  values: number[];
  setters: ((v: number) => void)[];
}

function BorneBlock({ mode, theme: t, enabled, values, setters }: BlockProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold text-slate-200">
          Cap dur val/h par classe HERE
          <span className="text-slate-500 font-normal ml-2">
            (BORNE_{t.label}_FC)
          </span>
        </span>
      </div>
      <p className="text-[10px] text-slate-400 mb-3">
        Borne absolue de val/h qu&apos;un segment peut atteindre en pointe{" "}
        {mode === "hpm" ? "matin" : "soir"} selon sa classe fonctionnelle.
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {FC_LABELS.map((fc, idx) => {
          const dflt =
            t.bornesDefaults[`fc${fc.key}` as keyof typeof t.bornesDefaults];
          const value = values[idx];
          const setter = setters[idx];
          const modified = value !== dflt;
          return (
            <div
              key={`borne-${mode}-${fc.key}`}
              className={`rounded-lg p-2.5 border transition-colors ${
                modified
                  ? `${t.cardBg} ${t.cardBorder}`
                  : "bg-surface-light/40 border-white/[0.05]"
              }`}
              title={`Defaut Lyon : ${dflt.toLocaleString("fr-FR")} val/h`}
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className={`text-[10px] font-mono font-semibold ${t.cardText}`}
                >
                  {fc.label}
                </span>
                {modified && (
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${t.cardDot}`}
                    title={`Modifie (defaut : ${dflt.toLocaleString("fr-FR")})`}
                  />
                )}
              </div>
              <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                {fc.type}
              </p>
              <input
                type="number"
                min={0}
                max={100000}
                step={100}
                value={value}
                onChange={(e) =>
                  setter(sanitizePositive(e.target.value, 100000))
                }
                disabled={!enabled}
                className={`w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none ${t.cardFocus} disabled:cursor-not-allowed`}
              />
              <p className="text-[9px] text-slate-500 mt-1">val/h</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AlphaBlock({ mode, theme: t, enabled, values, setters }: BlockProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-semibold text-slate-200">
          Ratio max {t.abbrev}/JOr par classe HERE
          <span className="text-slate-500 font-normal ml-2">
            (ALPHA_{t.label}_FC)
          </span>
        </span>
      </div>
      <p className="text-[10px] text-slate-400 mb-3">
        Plafond du ratio {t.abbrev}/JOr : le {t.abbrev} ne depassera jamais ce
        pourcentage du JOr (TV redresse) sur le segment.
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {FC_LABELS.map((fc, idx) => {
          const dflt =
            t.alphaDefaults[`fc${fc.key}` as keyof typeof t.alphaDefaults];
          const value = values[idx];
          const setter = setters[idx];
          const modified = value !== dflt;
          return (
            <div
              key={`alpha-${mode}-${fc.key}`}
              className={`rounded-lg p-2.5 border transition-colors ${
                modified
                  ? `${t.cardBg} ${t.cardBorder}`
                  : "bg-surface-light/40 border-white/[0.05]"
              }`}
              title={`Defaut Lyon : ${dflt}% (${t.abbrev} <= ${dflt}% du JOr)`}
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className={`text-[10px] font-mono font-semibold ${t.cardText}`}
                >
                  {fc.label}
                </span>
                {modified && (
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${t.cardDot}`}
                    title={`Modifie (defaut : ${dflt}%)`}
                  />
                )}
              </div>
              <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                {fc.type}
              </p>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={value}
                onChange={(e) => setter(sanitizePositive(e.target.value, 100))}
                disabled={!enabled}
                className={`w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none ${t.cardFocus} disabled:cursor-not-allowed`}
              />
              <p className="text-[9px] text-slate-500 mt-1">
                % ({t.abbrev}/JOr)
              </p>
            </div>
          );
        })}
      </div>
      <p className={`text-[10px] ${t.textWeak}/70 mt-2 italic`}>
        Le {t.abbrev} ne depassera jamais X% du JOr (TV redresse) sur ce type de
        voie.
      </p>
    </div>
  );
}
