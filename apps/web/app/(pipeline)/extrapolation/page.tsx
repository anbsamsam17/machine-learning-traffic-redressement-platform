"use client";

/**
 * Etape Extrapolation — predictions sur un nouveau territoire.
 *
 * Premiere version visuelle (UX2.0) : trois etapes verticales animees,
 * la carte etant activee une fois (1) un modele selectionne, (2) une zone
 * uploadee. Le backend pour l'inference batch n'etant pas encore branche,
 * la generation appelle ici un placeholder cote serveur (sans regression
 * — pas d'API existante a casser). La logique sera completee lorsque le
 * pipeline d'extrapolation sera disponible.
 */

import { useState } from "react";
import Link from "next/link";
import {
  Sparkles,
  Cpu,
  Map as MapIcon,
  Wand2,
  Upload,
  ArrowRight,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { useAppStore } from "@/lib/store";
import {
  GlowCardPremium,
  MagneticButton,
  NeonBorder,
  RevealOnScroll,
  ShimmerText,
  StatBadge,
} from "@/components/ui";

type Step = "model" | "zone" | "run";

function StepNumber({ index, active }: { index: number; active: boolean }) {
  return (
    <span
      className={
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-xs font-bold tabular-nums transition-colors " +
        (active
          ? "bg-accent border-accent text-accent-fg"
          : "bg-bg-elevated border-border text-text-muted")
      }
      aria-hidden="true"
    >
      {index}
    </span>
  );
}

export default function ExtrapolationPage() {
  const { mode, sessionId, outputDir } = useAppStore();
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [zoneFileName, setZoneFileName] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const modelReady = selectedModel.trim().length > 0;
  const zoneReady = zoneFileName !== null;
  const canRun = modelReady && zoneReady && !running;

  // Active step computation — guide visuelle, l'utilisateur reste libre.
  const activeStep: Step = !modelReady ? "model" : !zoneReady ? "zone" : "run";

  async function handleRun() {
    if (!canRun) return;
    setRunning(true);
    try {
      // Placeholder — branchera l'endpoint /api/extrapolation/run quand
      // disponible. On simule ici pour ne pas bloquer la demo visuelle.
      await new Promise((r) => setTimeout(r, 1200));
      toast.success(
        `Extrapolation generee pour ${zoneFileName ?? "la zone"} (mode ${
          mode?.toUpperCase() ?? "TV"
        })`,
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Erreur lors de la generation",
      );
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <RevealOnScroll variant="fade" stagger={0.05}>
        <div className="space-y-2">
          <ShimmerText as="h1" variant="cyan" className="text-2xl sm:text-3xl">
            Extrapolation
          </ShimmerText>
          <p className="text-sm text-text-muted">
            Generez des predictions de trafic pour un nouveau territoire a
            partir d&apos;un modele entraine. Trois etapes : selection du
            modele, upload de la zone, generation.
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <StatBadge
              label="Mode"
              value={
                mode === "pl"
                  ? "PL"
                  : mode === "hpm"
                    ? "HPM"
                    : mode === "hps"
                      ? "HPS"
                      : "TV"
              }
              tone="violet"
              size="sm"
            />
            {sessionId && (
              <StatBadge
                label="Session"
                value="Active"
                tone="success"
                size="sm"
              />
            )}
            {outputDir && (
              <StatBadge
                label="Workspace"
                value={
                  outputDir.length > 28
                    ? `...${outputDir.slice(-26)}`
                    : outputDir
                }
                tone="cyan"
                size="sm"
              />
            )}
          </div>
        </div>
      </RevealOnScroll>

      {/* Etape 1 — Modele */}
      <RevealOnScroll variant="slide-up" stagger={0.1}>
        <div data-reveal>
          {activeStep === "model" ? (
            <NeonBorder tone="cyan" speed={3} thickness={1}>
              <div className="p-5">
                <div className="flex items-center gap-3 mb-4">
                  <StepNumber index={1} active />
                  <Cpu size={18} className="text-[#22d3ee]" />
                  <h3 className="text-sm font-semibold text-text">
                    Selection du modele
                  </h3>
                  <StatBadge
                    label="Etape"
                    value="1/3"
                    tone="cyan"
                    size="sm"
                    className="ml-auto"
                  />
                </div>
                <p className="text-xs text-text-muted mb-3">
                  Renseigne le nom du modele entraine que tu souhaites utiliser
                  pour generer les predictions.
                </p>
                <input
                  type="text"
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  placeholder="ex. D4_8643_bs128_ep1500"
                  className="w-full px-3 h-10 rounded-md text-sm bg-bg-elevated border border-border text-text font-mono focus:outline-none focus:border-[#22d3ee] focus:ring-1 focus:ring-[#22d3ee]/40 transition-colors"
                />
              </div>
            </NeonBorder>
          ) : (
            <GlowCardPremium tone="cyan" intensity={0.3}>
              <div className="flex items-center gap-3">
                <StepNumber index={1} active={false} />
                <Cpu size={18} className="text-text-muted" />
                <span className="text-sm font-medium text-text-muted">
                  Modele :{" "}
                  <span className="font-mono text-text">{selectedModel}</span>
                </span>
                <button
                  type="button"
                  onClick={() => setSelectedModel("")}
                  className="ml-auto text-xs text-text-subtle hover:text-text underline-offset-2 hover:underline"
                >
                  Modifier
                </button>
              </div>
            </GlowCardPremium>
          )}
        </div>
      </RevealOnScroll>

      {/* Etape 2 — Zone */}
      <RevealOnScroll variant="slide-up" stagger={0.1} delay={0.1}>
        <div data-reveal>
          {activeStep === "zone" ? (
            <NeonBorder tone="cyan" speed={3} thickness={1}>
              <div className="p-5">
                <div className="flex items-center gap-3 mb-4">
                  <StepNumber index={2} active />
                  <MapIcon size={18} className="text-[#22d3ee]" />
                  <h3 className="text-sm font-semibold text-text">
                    Zone a extrapoler
                  </h3>
                  <StatBadge
                    label="Etape"
                    value="2/3"
                    tone="cyan"
                    size="sm"
                    className="ml-auto"
                  />
                </div>
                <p className="text-xs text-text-muted mb-3">
                  Depose un fichier GeoJSON / CSV contenant les segments du
                  nouveau territoire (memes colonnes que le fichier
                  d&apos;entrainement).
                </p>
                <label
                  htmlFor="extrap-zone-input"
                  className="flex items-center justify-center gap-3 px-4 py-6 rounded-lg border-2 border-dashed border-border bg-bg-elevated/40 cursor-pointer hover:border-[#22d3ee]/50 hover:bg-[rgba(34,211,238,0.04)] transition-colors"
                >
                  <Upload size={18} className="text-[#22d3ee]" />
                  <span className="text-sm text-text-muted">
                    Cliquez ou deposez un fichier zone
                  </span>
                </label>
                <input
                  id="extrap-zone-input"
                  type="file"
                  accept=".geojson,.json,.csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) setZoneFileName(f.name);
                  }}
                />
              </div>
            </NeonBorder>
          ) : modelReady ? (
            <GlowCardPremium
              tone={zoneReady ? "cyan" : "accent"}
              intensity={zoneReady ? 0.3 : 0.55}
            >
              <div className="flex items-center gap-3">
                <StepNumber index={2} active={false} />
                <MapIcon size={18} className="text-text-muted" />
                <span className="text-sm font-medium text-text-muted">
                  Zone :{" "}
                  {zoneReady ? (
                    <span className="font-mono text-text">{zoneFileName}</span>
                  ) : (
                    <span className="italic text-text-subtle">
                      en attente du modele
                    </span>
                  )}
                </span>
                {zoneReady && (
                  <button
                    type="button"
                    onClick={() => setZoneFileName(null)}
                    className="ml-auto text-xs text-text-subtle hover:text-text underline-offset-2 hover:underline"
                  >
                    Changer
                  </button>
                )}
              </div>
            </GlowCardPremium>
          ) : (
            <GlowCardPremium tone="accent" intensity={0.2}>
              <div className="flex items-center gap-3 opacity-60">
                <StepNumber index={2} active={false} />
                <MapIcon size={18} className="text-text-subtle" />
                <span className="text-sm text-text-subtle italic">
                  Selectionne d&apos;abord un modele
                </span>
              </div>
            </GlowCardPremium>
          )}
        </div>
      </RevealOnScroll>

      {/* Etape 3 — Generation */}
      <RevealOnScroll variant="slide-up" stagger={0.1} delay={0.2}>
        <div data-reveal>
          {activeStep === "run" ? (
            <NeonBorder tone={running ? "amber" : "cyan"} speed={2.4}>
              <div className="p-5">
                <div className="flex items-center gap-3 mb-4">
                  <StepNumber index={3} active />
                  <Wand2 size={18} className="text-[#22d3ee]" />
                  <h3 className="text-sm font-semibold text-text">
                    Generation des predictions
                  </h3>
                  <StatBadge
                    label="Etape"
                    value="3/3"
                    tone={running ? "amber" : "cyan"}
                    size="sm"
                    className="ml-auto"
                  />
                </div>
                <p className="text-xs text-text-muted mb-4">
                  Le pipeline applique le modele <span className="font-mono text-text">{selectedModel}</span>{" "}
                  sur les segments de <span className="font-mono text-text">{zoneFileName}</span>{" "}
                  et exporte un GeoJSON enrichi.
                </p>
                <div className="flex justify-end">
                  <MagneticButton
                    variant="primary"
                    size="lg"
                    onClick={handleRun}
                    disabled={!canRun}
                  >
                    {running ? (
                      <Loader2 size={18} className="animate-spin" />
                    ) : (
                      <Sparkles size={18} />
                    )}
                    {running ? "Generation en cours..." : "Lancer la generation"}
                  </MagneticButton>
                </div>
              </div>
            </NeonBorder>
          ) : (
            <GlowCardPremium tone="accent" intensity={0.2}>
              <div className="flex items-center gap-3 opacity-60">
                <StepNumber index={3} active={false} />
                <Wand2 size={18} className="text-text-subtle" />
                <span className="text-sm text-text-subtle italic">
                  Selectionne un modele et une zone pour activer
                </span>
              </div>
            </GlowCardPremium>
          )}
        </div>
      </RevealOnScroll>

      {/* Aide */}
      <RevealOnScroll variant="fade" delay={0.3}>
        <div className="rounded-md border border-border bg-bg-elevated/60 p-4">
          <p className="text-xs text-text-muted">
            Astuce — si tu n&apos;as pas encore de modele entraine, passe par{" "}
            <Link
              href="/training"
              className="text-accent hover:underline inline-flex items-center gap-1"
            >
              l&apos;etape Entrainement
              <ArrowRight size={11} />
            </Link>{" "}
            avant de revenir ici.
          </p>
        </div>
      </RevealOnScroll>
    </div>
  );
}
