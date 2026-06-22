"use client";

import { useCallback } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Info,
  Loader2,
  RotateCcw,
  ShieldAlert,
  X,
} from "lucide-react";
import { DropZone } from "@/components/upload/drop-zone";
import {
  FC_LABELS,
  PL_SAT_ALPHA_DEFAULTS,
  PL_SAT_BORNES_DEFAULTS,
  PL_SAT_V2_DEFAULTS,
} from "@/lib/carte/defaults";
import type { CapteursPlInfo } from "@/lib/carte/types";

// ---------------------------------------------------------------------------
// PlSaturationPanel
// ---------------------------------------------------------------------------
// Panel saturation PL v3 (BORNES, ALPHA, hyperparams v2, override v3 + upload
// SIREDO). Controlled : tout le state vient du parent via props pour ne rien
// dupliquer (la page reste source de verite pour la generation API).
// ---------------------------------------------------------------------------

export interface PlSaturationPanelProps {
  // Toggle global
  plSatEnabled: boolean;
  onPlSatEnabledChange: (v: boolean) => void;

  // BORNES_FC_ABS
  bornesFc1: number;
  bornesFc2: number;
  bornesFc3: number;
  bornesFc4: number;
  bornesFc5: number;
  onBornesFc1Change: (v: number) => void;
  onBornesFc2Change: (v: number) => void;
  onBornesFc3Change: (v: number) => void;
  onBornesFc4Change: (v: number) => void;
  onBornesFc5Change: (v: number) => void;

  // ALPHA_FC_MIN
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

  // Hyperparams v2
  ratioMacroPen: number;
  alphaPhysiqueMax: number;
  seuilVolFcdTv: number;
  onRatioMacroPenChange: (v: number) => void;
  onAlphaPhysiqueMaxChange: (v: number) => void;
  onSeuilVolFcdTvChange: (v: number) => void;

  // v3 zones critiques
  zoneCritEnabled: boolean;
  onZoneCritEnabledChange: (v: boolean) => void;
  capteursPlSessionId: string | null;
  capteursPlName: string | null;
  capteursPlInfo: CapteursPlInfo | null;
  capteursPlUploading: boolean;
  onCapteursPlUpload: (file: File) => void;
  onCapteursPlClear: () => void;

  anneeCapteurs: number;
  onAnneeCapteursChange: (v: number) => void;
  ratioCapteurCritique: number;
  onRatioCapteurCritiqueChange: (v: number) => void;
  bufferZoneCritiqueM: number;
  onBufferZoneCritiqueMChange: (v: number) => void;
  alphaMinZoneCritique: number;
  onAlphaMinZoneCritiqueChange: (v: number) => void;

  // Etat global
  plSatModified: boolean;
  onReset: () => void;
}

// Sanitize : >= 0, NaN -> 0, garde max raisonnable
function sanitizePositive(raw: string, max: number): number {
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.min(n, max);
}

export function PlSaturationPanel(props: PlSaturationPanelProps) {
  const {
    plSatEnabled,
    onPlSatEnabledChange,
    bornesFc1,
    bornesFc2,
    bornesFc3,
    bornesFc4,
    bornesFc5,
    onBornesFc1Change,
    onBornesFc2Change,
    onBornesFc3Change,
    onBornesFc4Change,
    onBornesFc5Change,
    alphaFc1,
    alphaFc2,
    alphaFc3,
    alphaFc4,
    alphaFc5,
    onAlphaFc1Change,
    onAlphaFc2Change,
    onAlphaFc3Change,
    onAlphaFc4Change,
    onAlphaFc5Change,
    ratioMacroPen,
    alphaPhysiqueMax,
    seuilVolFcdTv,
    onRatioMacroPenChange,
    onAlphaPhysiqueMaxChange,
    onSeuilVolFcdTvChange,
    zoneCritEnabled,
    onZoneCritEnabledChange,
    capteursPlSessionId,
    capteursPlName,
    capteursPlInfo,
    capteursPlUploading,
    onCapteursPlUpload,
    onCapteursPlClear,
    anneeCapteurs,
    onAnneeCapteursChange,
    ratioCapteurCritique,
    onRatioCapteurCritiqueChange,
    bufferZoneCritiqueM,
    onBufferZoneCritiqueMChange,
    alphaMinZoneCritique,
    onAlphaMinZoneCritiqueChange,
    plSatModified,
    onReset,
  } = props;

  const sanitize = useCallback(
    (raw: string, max: number) => sanitizePositive(raw, max),
    [],
  );

  return (
    <div className="mt-8 pt-6 border-t border-white/[0.06]">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <ShieldAlert size={14} className="text-amber-400" />
          <span className="text-xs font-medium text-slate-200">
            Saturation hierarchique PL
          </span>
          <span
            className="ml-1 text-[10px] font-mono text-cyan-300 border border-cyan-500/40 rounded px-1.5 py-0.5"
            title="Strategie v3 hybride + override zones critiques (capteurs SIREDO PL)"
          >
            v3
          </span>
          {plSatModified && plSatEnabled && (
            <span
              className="text-[10px] text-amber-300 bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 rounded"
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
              plSatEnabled ? "text-amber-300" : "text-slate-500"
            }`}
          >
            {plSatEnabled ? "Activee" : "Desactivee"}
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={plSatEnabled}
            onClick={() => onPlSatEnabledChange(!plSatEnabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400/50 ${
              plSatEnabled
                ? "bg-amber-500/70 shadow-[0_0_8px_rgba(251,191,36,0.4)]"
                : "bg-slate-700"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                plSatEnabled ? "translate-x-5" : "translate-x-1"
              }`}
            />
          </button>
        </label>
      </div>

      <p className="text-[11px] text-slate-400 leading-relaxed mb-4">
        Saturation hierarchique{" "}
        <span className="text-cyan-300">
          v3 hybride adaptative + override zones critiques
        </span>
        . Le ratio max PL/JOr est calcule par segment depuis le FCD local, avec
        plancher = bornes v1 par FC, plafond physique 0.55, et override 0.30
        dans les zones ou des capteurs SIREDO montrent un ratio PL eleve.
        Calibre sur 991 capteurs Lyon 2025.
      </p>

      {!plSatEnabled && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/20 text-amber-300/80 text-[11px]">
          <Info size={12} className="mt-0.5 flex-shrink-0" />
          <span>
            La saturation est desactivee. Les valeurs PL brutes du modele seront
            conservees telles quelles (peut produire des valeurs aberrantes).
          </span>
        </div>
      )}

      <div
        className={`space-y-6 transition-opacity ${
          plSatEnabled ? "opacity-100" : "opacity-50 pointer-events-none"
        }`}
        aria-disabled={!plSatEnabled}
      >
        {/* Encart pedagogique : explication v2 hybride adaptative */}
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] p-3 text-[11px] text-slate-300 leading-relaxed">
          <strong className="text-amber-300">Strategie v2 hybride :</strong>{" "}
          pour chaque segment, on calcule un ratio adaptatif base sur le FCD
          local (
          <code className="text-amber-300">
            α_FCD = TMJFCDPL/TMJFCDTV × {ratioMacroPen.toFixed(3)}
          </code>
          ). Le ratio final est encadre par&nbsp;:
          <span className="text-amber-300">
            {" "}
            plancher = α_FC_min[FC]
          </span>{" "}
          (= bornes v1, garde-fou bas) ET
          <span className="text-amber-300">
            {" "}
            plafond = {alphaPhysiqueMax}%
          </span>{" "}
          (limite physique). Si <code>TMJFCDTV &lt; {seuilVolFcdTv}</code>{" "}
          veh/j, on retombe sur le plancher (FCD trop bruite).
        </div>

        {/* Sous-bloc 1 : BORNES_FC_ABS */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold text-slate-200">
              Cap absolu PL/jour par classe HERE
              <span className="text-slate-500 font-normal ml-2">
                (BORNES_FC_ABS)
              </span>
            </span>
          </div>
          <p className="text-[10px] text-slate-400 mb-3">
            Borne absolue de PL/jour qu&apos;un segment peut atteindre selon sa
            classe fonctionnelle, quel que soit le JOr (TV redresse). Inchange
            en valeur depuis v1, juste renomme pour clarifier le role de cap
            dur independant du ratio.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {(() => {
              const items = [
                {
                  fc: FC_LABELS[0],
                  value: bornesFc1,
                  setter: onBornesFc1Change,
                  dflt: PL_SAT_BORNES_DEFAULTS.fc1,
                },
                {
                  fc: FC_LABELS[1],
                  value: bornesFc2,
                  setter: onBornesFc2Change,
                  dflt: PL_SAT_BORNES_DEFAULTS.fc2,
                },
                {
                  fc: FC_LABELS[2],
                  value: bornesFc3,
                  setter: onBornesFc3Change,
                  dflt: PL_SAT_BORNES_DEFAULTS.fc3,
                },
                {
                  fc: FC_LABELS[3],
                  value: bornesFc4,
                  setter: onBornesFc4Change,
                  dflt: PL_SAT_BORNES_DEFAULTS.fc4,
                },
                {
                  fc: FC_LABELS[4],
                  value: bornesFc5,
                  setter: onBornesFc5Change,
                  dflt: PL_SAT_BORNES_DEFAULTS.fc5,
                },
              ];
              return items.map(({ fc, value, setter, dflt }) => {
                const modified = value !== dflt;
                return (
                  <div
                    key={`bornes-${fc.key}`}
                    className={`rounded-lg p-2.5 border transition-colors ${
                      modified
                        ? "bg-amber-500/5 border-amber-500/30"
                        : "bg-surface-light/40 border-white/[0.05]"
                    }`}
                    title={`Defaut Lyon : ${dflt.toLocaleString("fr-FR")} PL/j`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono font-semibold text-amber-300">
                        {fc.label}
                      </span>
                      {modified && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-amber-400"
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
                      onChange={(e) => setter(sanitize(e.target.value, 100000))}
                      disabled={!plSatEnabled}
                      className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-amber-400/50 disabled:cursor-not-allowed"
                    />
                    <p className="text-[9px] text-slate-500 mt-1">PL/jour</p>
                  </div>
                );
              });
            })()}
          </div>
        </div>

        {/* Sous-bloc 2 : ALPHA_FC_MIN */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold text-slate-200">
              Plancher du ratio PL/JOr par classe HERE (α_FC_min)
              <span className="text-slate-500 font-normal ml-2">
                (ALPHA_FC_MIN)
              </span>
            </span>
          </div>
          <p className="text-[10px] text-slate-400 mb-3">
            Plancher local par defaut (= bornes v1). Le ratio adaptatif ne
            descendra jamais en dessous. Garde-fou bas pour les segments ou le
            FCD local sous-estime la presence PL.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {(() => {
              const items = [
                {
                  fc: FC_LABELS[0],
                  value: alphaFc1,
                  setter: onAlphaFc1Change,
                  dflt: PL_SAT_ALPHA_DEFAULTS.fc1,
                },
                {
                  fc: FC_LABELS[1],
                  value: alphaFc2,
                  setter: onAlphaFc2Change,
                  dflt: PL_SAT_ALPHA_DEFAULTS.fc2,
                },
                {
                  fc: FC_LABELS[2],
                  value: alphaFc3,
                  setter: onAlphaFc3Change,
                  dflt: PL_SAT_ALPHA_DEFAULTS.fc3,
                },
                {
                  fc: FC_LABELS[3],
                  value: alphaFc4,
                  setter: onAlphaFc4Change,
                  dflt: PL_SAT_ALPHA_DEFAULTS.fc4,
                },
                {
                  fc: FC_LABELS[4],
                  value: alphaFc5,
                  setter: onAlphaFc5Change,
                  dflt: PL_SAT_ALPHA_DEFAULTS.fc5,
                },
              ];
              return items.map(({ fc, value, setter, dflt }) => {
                const modified = value !== dflt;
                return (
                  <div
                    key={`alpha-${fc.key}`}
                    className={`rounded-lg p-2.5 border transition-colors ${
                      modified
                        ? "bg-amber-500/5 border-amber-500/30"
                        : "bg-surface-light/40 border-white/[0.05]"
                    }`}
                    title={`Defaut Lyon : ${dflt}% (PL <= ${dflt}% du TV)`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono font-semibold text-amber-300">
                        {fc.label}
                      </span>
                      {modified && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-amber-400"
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
                      onChange={(e) => setter(sanitize(e.target.value, 100))}
                      disabled={!plSatEnabled}
                      className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-amber-400/50 disabled:cursor-not-allowed"
                    />
                    <p className="text-[9px] text-slate-500 mt-1">% (PL/JOr)</p>
                  </div>
                );
              });
            })()}
          </div>
          <p className="text-[10px] text-amber-300/70 mt-2 italic">
            Le PL ne depassera jamais X% du JOr (TV redresse) sur ce type de
            voie.
          </p>
        </div>

        {/* Sous-bloc 3 : Hyperparamètres v2 hybride adaptative */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold text-slate-200">
              Hyperparametres v2 hybride
              <span className="text-slate-500 font-normal ml-2">
                (macro penetration, plafond physique, seuil bruit FCD)
              </span>
            </span>
          </div>
          <p className="text-[10px] text-slate-400 mb-3">
            Parametres globaux du calcul adaptatif. Le ratio FCD local (
            <span className="font-mono text-amber-400/90">
              TMJFCDPL/TMJFCDTV
            </span>
            ) est multiplie par le facteur de pen. macro, puis encadre par les
            bornes plancher (FC) / plafond (physique).
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {/* a) ratio_macro_pen */}
            {(() => {
              const modified = ratioMacroPen !== PL_SAT_V2_DEFAULTS.ratioMacroPen;
              return (
                <div
                  className={`rounded-lg p-2.5 border transition-colors ${
                    modified
                      ? "bg-amber-500/5 border-amber-500/30"
                      : "bg-surface-light/40 border-white/[0.05]"
                  }`}
                  title={`Defaut Lyon : ${PL_SAT_V2_DEFAULTS.ratioMacroPen}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-mono font-semibold text-amber-300">
                      Ratio macro penetration
                    </span>
                    {modified && (
                      <span
                        className="w-1.5 h-1.5 rounded-full bg-amber-400"
                        title={`Modifie (defaut : ${PL_SAT_V2_DEFAULTS.ratioMacroPen})`}
                      />
                    )}
                  </div>
                  <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                    Corrige le biais TxPen TV vs PL (Lyon 2025 : 2.24%/1.97% =
                    1.137)
                  </p>
                  <input
                    type="number"
                    min={0.5}
                    max={2.0}
                    step={0.001}
                    value={ratioMacroPen}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      if (Number.isFinite(n))
                        onRatioMacroPenChange(Math.max(0.5, Math.min(2.0, n)));
                    }}
                    disabled={!plSatEnabled}
                    className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-amber-400/50 disabled:cursor-not-allowed"
                  />
                  <p className="text-[9px] text-slate-500 mt-1">
                    facteur (sans unite)
                  </p>
                </div>
              );
            })()}

            {/* b) alpha_physique_max */}
            {(() => {
              const modified =
                alphaPhysiqueMax !== PL_SAT_V2_DEFAULTS.alphaPhysiqueMax;
              return (
                <div
                  className={`rounded-lg p-2.5 border transition-colors ${
                    modified
                      ? "bg-amber-500/5 border-amber-500/30"
                      : "bg-surface-light/40 border-white/[0.05]"
                  }`}
                  title={`Defaut Lyon : ${PL_SAT_V2_DEFAULTS.alphaPhysiqueMax}% (plafond biomecanique CEREMA)`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-mono font-semibold text-amber-300">
                      Plafond physique du ratio PL/JOr
                    </span>
                    {modified && (
                      <span
                        className="w-1.5 h-1.5 rounded-full bg-amber-400"
                        title={`Modifie (defaut : ${PL_SAT_V2_DEFAULTS.alphaPhysiqueMax}%)`}
                      />
                    )}
                  </div>
                  <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                    Limite biomecanique CEREMA (au-dela = aberration)
                  </p>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={alphaPhysiqueMax}
                    onChange={(e) =>
                      onAlphaPhysiqueMaxChange(sanitize(e.target.value, 100))
                    }
                    disabled={!plSatEnabled}
                    className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-amber-400/50 disabled:cursor-not-allowed"
                  />
                  <p className="text-[9px] text-slate-500 mt-1">%</p>
                </div>
              );
            })()}

            {/* c) seuil_vol_fcd_tv */}
            {(() => {
              const modified = seuilVolFcdTv !== PL_SAT_V2_DEFAULTS.seuilVolFcdTv;
              return (
                <div
                  className={`rounded-lg p-2.5 border transition-colors ${
                    modified
                      ? "bg-amber-500/5 border-amber-500/30"
                      : "bg-surface-light/40 border-white/[0.05]"
                  }`}
                  title={`Defaut Lyon : ${PL_SAT_V2_DEFAULTS.seuilVolFcdTv} veh/j`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-mono font-semibold text-amber-300">
                      Seuil TMJFCDTV pour fallback plancher
                    </span>
                    {modified && (
                      <span
                        className="w-1.5 h-1.5 rounded-full bg-amber-400"
                        title={`Modifie (defaut : ${PL_SAT_V2_DEFAULTS.seuilVolFcdTv})`}
                      />
                    )}
                  </div>
                  <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                    Sous ce seuil, le ratio FCD est trop bruite -&gt; retombe
                    sur le plancher local
                  </p>
                  <input
                    type="number"
                    min={0}
                    max={10000}
                    step={1}
                    value={seuilVolFcdTv}
                    onChange={(e) =>
                      onSeuilVolFcdTvChange(sanitize(e.target.value, 10000))
                    }
                    disabled={!plSatEnabled}
                    className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-amber-400/50 disabled:cursor-not-allowed"
                  />
                  <p className="text-[9px] text-slate-500 mt-1">veh/jour</p>
                </div>
              );
            })()}
          </div>
        </div>

        {/* Sous-bloc 4 : Override zones critiques (v3) */}
        <div className="pt-4 border-t border-cyan-500/10">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-cyan-400" />
              <h4 className="text-sm font-semibold text-cyan-300">
                Override zones critiques (v3)
              </h4>
            </div>
            <label className="flex items-center gap-2 cursor-pointer group flex-shrink-0">
              <span
                className={`text-[11px] font-medium transition-colors ${
                  zoneCritEnabled ? "text-cyan-300" : "text-slate-500"
                }`}
              >
                {zoneCritEnabled ? "Activee" : "Desactivee"}
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={zoneCritEnabled}
                onClick={() => onZoneCritEnabledChange(!zoneCritEnabled)}
                disabled={!plSatEnabled}
                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-cyan-400/50 disabled:opacity-50 disabled:cursor-not-allowed ${
                  zoneCritEnabled
                    ? "bg-cyan-500/70 shadow-[0_0_8px_rgba(34,211,238,0.4)]"
                    : "bg-slate-700"
                }`}
              >
                <span
                  className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                    zoneCritEnabled ? "translate-x-5" : "translate-x-1"
                  }`}
                />
              </button>
            </label>
          </div>

          <p className="text-[11px] text-slate-400 leading-relaxed mb-3">
            Detecte automatiquement les zones critiques via les capteurs SIREDO
            PL (ratio observe &gt; 15&nbsp;% + buffer 1&nbsp;km). Dans ces
            zones, le plancher du ratio PL/JOr est releve a 30&nbsp;%.
            Desactiver = comportement v2 (hybride sans zones critiques).
          </p>

          {/* Indicateur d'etat v3 (Phase 8) */}
          <div className="mb-4">
            {zoneCritEnabled && capteursPlSessionId ? (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-cyan-500/5 border border-cyan-500/30 text-cyan-300 text-[11px]">
                <CheckCircle2 size={12} className="mt-0.5 flex-shrink-0" />
                <span>
                  v3 actif (zones critiques detectees avec capteurs SIREDO)
                </span>
              </div>
            ) : zoneCritEnabled && !capteursPlSessionId ? (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/30 text-amber-300/90 text-[11px]">
                <AlertCircle size={12} className="mt-0.5 flex-shrink-0" />
                <span>
                  v3 inactif : charge le fichier capteurs SIREDO pour activer
                </span>
              </div>
            ) : (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-slate-500/5 border border-slate-500/20 text-slate-400 text-[11px]">
                <Info size={12} className="mt-0.5 flex-shrink-0" />
                <span>Comportement v2 (hybride sans zones critiques)</span>
              </div>
            )}
          </div>

          {/* Dropzone d'upload BCFCDREF_AllYears_PL.geojson */}
          <div
            className={`mb-4 transition-opacity ${
              zoneCritEnabled ? "opacity-100" : "opacity-50 pointer-events-none"
            }`}
          >
            <p className="text-[10px] font-semibold text-slate-300 mb-2">
              Capteurs SIREDO PL (BCFCDREF_AllYears_PL.geojson)
            </p>
            {capteursPlSessionId && capteursPlName ? (
              <div className="flex items-center gap-3 p-3 rounded-xl border border-cyan-500/30 bg-cyan-500/[0.04]">
                <div className="w-9 h-9 rounded-lg bg-cyan-500/10 flex items-center justify-center text-cyan-300 flex-shrink-0">
                  <CheckCircle2 size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-slate-100 truncate">
                    {capteursPlName}
                  </p>
                  {capteursPlInfo && (
                    <p className="text-[10px] text-cyan-300/80 mt-0.5">
                      {capteursPlInfo.n_capteurs.toLocaleString("fr-FR")}{" "}
                      capteurs charges
                      {capteursPlInfo.annees_disponibles.length > 0 && (
                        <>
                          {" "}
                          (annees :{" "}
                          {capteursPlInfo.annees_disponibles.join(", ")})
                        </>
                      )}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={onCapteursPlClear}
                  className="p-1.5 rounded-lg hover:bg-red-500/10 text-slate-400 hover:text-red-400 transition-colors"
                  title="Retirer le fichier capteurs"
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <>
                <DropZone
                  file={null}
                  onFile={onCapteursPlUpload}
                  onClear={onCapteursPlClear}
                  accept={{
                    "application/json": [".geojson", ".json"],
                    "application/geo+json": [".geojson"],
                  }}
                  label="Deposez BCFCDREF_AllYears_PL.geojson"
                  description=".geojson ou .json (capteurs SIREDO PL)"
                />
                {capteursPlUploading && (
                  <div className="flex items-center gap-2 mt-2 text-[11px] text-cyan-300/80">
                    <Loader2 size={12} className="animate-spin" />
                    <span>Chargement du fichier capteurs SIREDO...</span>
                  </div>
                )}
                {!capteursPlUploading && (
                  <p className="text-[10px] text-slate-500 mt-2 italic">
                    Pas de fichier charge -&gt; fallback v2 silencieux (sans
                    zones critiques)
                  </p>
                )}
              </>
            )}
          </div>

          {/* 4 inputs parametres v3 — visibles seulement si zone_crit_enabled + capteurs charges */}
          {zoneCritEnabled && capteursPlSessionId && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {/* a) annee_capteurs */}
              {(() => {
                const modified = anneeCapteurs !== 2025;
                const hasOptions =
                  capteursPlInfo &&
                  capteursPlInfo.annees_disponibles.length > 0;
                return (
                  <div
                    className={`rounded-lg p-2.5 border transition-colors ${
                      modified
                        ? "bg-cyan-500/5 border-cyan-500/30"
                        : "bg-surface-light/40 border-white/[0.05]"
                    }`}
                    title="Annee de reference des capteurs SIREDO PL"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono font-semibold text-cyan-300">
                        Annee de reference
                      </span>
                      {modified && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-cyan-400"
                          title="Modifie (defaut : 2025)"
                        />
                      )}
                    </div>
                    <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                      Annee SIREDO utilisee pour le calcul du ratio capteur
                    </p>
                    {hasOptions ? (
                      <select
                        value={anneeCapteurs}
                        onChange={(e) =>
                          onAnneeCapteursChange(Number(e.target.value))
                        }
                        disabled={!plSatEnabled}
                        className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50 disabled:cursor-not-allowed"
                      >
                        {capteursPlInfo!.annees_disponibles
                          .slice()
                          .sort((a, b) => b - a)
                          .map((a) => (
                            <option key={a} value={a}>
                              {a}
                            </option>
                          ))}
                      </select>
                    ) : (
                      <input
                        type="number"
                        min={2000}
                        max={2099}
                        step={1}
                        value={anneeCapteurs}
                        onChange={(e) => {
                          const n = Number(e.target.value);
                          if (Number.isFinite(n))
                            onAnneeCapteursChange(
                              Math.max(2000, Math.min(2099, n)),
                            );
                        }}
                        disabled={!plSatEnabled}
                        className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50 disabled:cursor-not-allowed"
                      />
                    )}
                    <p className="text-[9px] text-slate-500 mt-1">annee</p>
                  </div>
                );
              })()}

              {/* b) ratio_capteur_critique */}
              {(() => {
                const modified = ratioCapteurCritique !== 15;
                return (
                  <div
                    className={`rounded-lg p-2.5 border transition-colors ${
                      modified
                        ? "bg-cyan-500/5 border-cyan-500/30"
                        : "bg-surface-light/40 border-white/[0.05]"
                    }`}
                    title="Defaut Lyon : 15% (capteurs critiques)"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono font-semibold text-cyan-300">
                        Seuil ratio capteur critique
                      </span>
                      {modified && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-cyan-400"
                          title="Modifie (defaut : 15%)"
                        />
                      )}
                    </div>
                    <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                      Capteur SIREDO critique si TMJOBCPL/TMJOBCTV &gt; X%
                    </p>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={0.1}
                      value={ratioCapteurCritique}
                      onChange={(e) =>
                        onRatioCapteurCritiqueChange(
                          sanitize(e.target.value, 100),
                        )
                      }
                      disabled={!plSatEnabled}
                      className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50 disabled:cursor-not-allowed"
                    />
                    <p className="text-[9px] text-slate-500 mt-1">%</p>
                  </div>
                );
              })()}

              {/* c) buffer_zone_critique_m */}
              {(() => {
                const modified = bufferZoneCritiqueM !== 1000;
                return (
                  <div
                    className={`rounded-lg p-2.5 border transition-colors ${
                      modified
                        ? "bg-cyan-500/5 border-cyan-500/30"
                        : "bg-surface-light/40 border-white/[0.05]"
                    }`}
                    title="Defaut Lyon : 1000 m"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono font-semibold text-cyan-300">
                        Buffer autour des capteurs
                      </span>
                      {modified && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-cyan-400"
                          title="Modifie (defaut : 1000 m)"
                        />
                      )}
                    </div>
                    <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                      Distance d&apos;influence des capteurs critiques sur les
                      segments alentour
                    </p>
                    <input
                      type="number"
                      min={0}
                      max={10000}
                      step={100}
                      value={bufferZoneCritiqueM}
                      onChange={(e) =>
                        onBufferZoneCritiqueMChange(
                          sanitize(e.target.value, 10000),
                        )
                      }
                      disabled={!plSatEnabled}
                      className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50 disabled:cursor-not-allowed"
                    />
                    <p className="text-[9px] text-slate-500 mt-1">m</p>
                  </div>
                );
              })()}

              {/* d) alpha_min_zone_critique */}
              {(() => {
                const modified = alphaMinZoneCritique !== 30;
                return (
                  <div
                    className={`rounded-lg p-2.5 border transition-colors ${
                      modified
                        ? "bg-cyan-500/5 border-cyan-500/30"
                        : "bg-surface-light/40 border-white/[0.05]"
                    }`}
                    title="Defaut Lyon : 30% (plancher zones critiques)"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-mono font-semibold text-cyan-300">
                        Plancher local zones critiques
                      </span>
                      {modified && (
                        <span
                          className="w-1.5 h-1.5 rounded-full bg-cyan-400"
                          title="Modifie (defaut : 30%)"
                        />
                      )}
                    </div>
                    <p className="text-[9px] text-slate-400 mb-1.5 leading-tight">
                      Ratio PL/JOr minimum dans les zones identifiees comme
                      critiques
                    </p>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={0.5}
                      value={alphaMinZoneCritique}
                      onChange={(e) =>
                        onAlphaMinZoneCritiqueChange(
                          sanitize(e.target.value, 100),
                        )
                      }
                      disabled={!plSatEnabled}
                      className="w-full h-7 rounded-md border border-border bg-surface/80 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50 disabled:cursor-not-allowed"
                    />
                    <p className="text-[9px] text-slate-500 mt-1">%</p>
                  </div>
                );
              })()}
            </div>
          )}
        </div>

        {/* Reset button */}
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onReset}
            disabled={!plSatEnabled || !plSatModified}
            className="flex items-center gap-1.5 text-[10px] font-medium text-amber-300/90 hover:text-amber-200 disabled:text-slate-600 disabled:cursor-not-allowed px-2.5 py-1.5 rounded-md border border-amber-500/30 hover:border-amber-400/60 disabled:border-white/[0.05] bg-amber-500/5 hover:bg-amber-500/10 disabled:bg-transparent transition-colors"
            title="Restaurer les valeurs par defaut calibrees Grand Lyon"
          >
            <RotateCcw size={11} />
            <span>Reinitialiser aux valeurs Lyon</span>
          </button>
        </div>
      </div>
    </div>
  );
}
