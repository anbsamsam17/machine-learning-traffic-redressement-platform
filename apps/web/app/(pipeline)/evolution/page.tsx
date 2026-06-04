"use client";

/**
 * Module "Carte d'evolution des debits".
 *
 * Deux cartes de debits redressees (annee1=T1, annee2=T2, base=T2) -> une
 * carte d'evolution par troncon exploitant la metrique JOr UNIQUEMENT.
 *
 * Flux :
 *   1. Upload des 2 cartes (file_t1, file_t2) -> POST /api/evolution/upload
 *      -> { session_id }.
 *   2. Options : use_ban (verification BAN N3), plancher_t1 (garde-fou
 *      emergent, defaut 50 v/j), include_new (emettre les troncons "nouveau").
 *   3. POST /api/evolution/generate -> traitement en background (matching N1
 *      cle exacte + N2 map-matching geometrique + N3 BAN, LONG).
 *   4. Polling GET /api/evolution/status/{id} -> progression.
 *   5. Visualiser (/evolution/visualiser/{id}) + Telecharger le GeoJSON.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  Download,
  GitCompareArrows,
  Layers,
  Loader2,
  Map as MapIcon,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";
import { GlowCard } from "@/components/ui/glow-card";
import { GradientText } from "@/components/ui/gradient-text";
import { NeonButton } from "@/components/ui/neon-button";
import {
  MagneticButton,
  NeonBorder,
  RevealOnScroll,
  ShimmerText,
  StatBadge,
} from "@/components/ui";
import { DropZone } from "@/components/upload/drop-zone";
import { apiClient } from "@/lib/api";
import { getApiBase } from "@/lib/api-url";

// ---------------------------------------------------------------------------
// Types — contrat backend /api/evolution/*
// ---------------------------------------------------------------------------

interface UploadResponse {
  session_id: string;
}

interface GenerateResponse {
  session_id: string;
  started: boolean;
}

/**
 * Statistiques agregees renvoyees par /status une fois done=true.
 * Contrat backend reel (cf api/routers/evolution) : n_total, n_cle,
 * n_geom_auto, n_geom_verif, n_non_match, n_sig + jor_min/median/max.
 * Pas d'index signature : on veut que tsc detecte un acces a une cle absente.
 */
interface EvolutionStats {
  n_total?: number;
  n_cle?: number;
  n_geom_auto?: number;
  n_geom_verif?: number;
  n_non_match?: number;
  n_sig?: number;
  jor_min?: number;
  jor_median?: number;
  jor_max?: number;
}

interface StatusResponse {
  stage: string;
  progress: number; // 0..100
  done: boolean;
  error: string | null;
  stats: EvolutionStats | null;
}

const ACCEPT_GEOJSON: Record<string, string[]> = {
  "application/json": [".geojson", ".json"],
  "application/geo+json": [".geojson"],
};

const POLL_INTERVAL_MS = 1500;
const NF_FR = new Intl.NumberFormat("fr-FR");

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EvolutionPage() {
  const router = useRouter();

  // Uploads
  const [fileT1, setFileT1] = useState<File | null>(null);
  const [fileT2, setFileT2] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Options
  const [useBan, setUseBan] = useState(true);
  const [plancherT1, setPlancherT1] = useState(50);
  const [includeNew, setIncludeNew] = useState(false);

  // Generation / polling
  const [generating, setGenerating] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [progress, setProgress] = useState(0);
  const [done, setDone] = useState(false);
  const [stats, setStats] = useState<EvolutionStats | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  // -------------------------------------------------------------------------
  // Upload des 2 cartes (multipart : file_t1, file_t2)
  // -------------------------------------------------------------------------
  const handleUpload = useCallback(async () => {
    if (!fileT1 || !fileT2) {
      toast.error("Chargez les deux cartes (annee 1 = T1 et annee 2 = T2/base).");
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file_t1", fileT1);
      form.append("file_t2", fileT2);
      const data = await apiClient.postForm<UploadResponse>(
        "/api/evolution/upload",
        form,
        { timeoutMs: 10 * 60_000 },
      );
      setSessionId(data.session_id);
      // Reset any previous run results when a new pair is uploaded.
      setDone(false);
      setStats(null);
      setProgress(0);
      setStage("");
      toast.success("Cartes T1 et T2 chargees. Vous pouvez generer l'evolution.");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Upload echoue : ${message}`);
    } finally {
      setUploading(false);
    }
  }, [fileT1, fileT2]);

  // -------------------------------------------------------------------------
  // Polling du statut (le calcul matching + BAN est LONG)
  // -------------------------------------------------------------------------
  const startPolling = useCallback(
    (id: string) => {
      stopPolling();
      const tick = async () => {
        try {
          const st = await apiClient.get<StatusResponse>(
            `/api/evolution/status/${encodeURIComponent(id)}`,
          );
          setStage(st.stage ?? "");
          setProgress(Math.max(0, Math.min(100, st.progress ?? 0)));

          if (st.error) {
            stopPolling();
            setGenerating(false);
            toast.error(`Generation echouee : ${st.error}`);
            return;
          }
          if (st.done) {
            stopPolling();
            setGenerating(false);
            setDone(true);
            setProgress(100);
            setStats(st.stats ?? null);
            toast.success("Carte d'evolution generee avec succes.");
          }
        } catch (err: unknown) {
          stopPolling();
          setGenerating(false);
          const message = err instanceof Error ? err.message : "Erreur inconnue";
          toast.error(`Suivi du statut interrompu : ${message}`);
        }
      };
      // immediate first tick, then interval
      void tick();
      pollRef.current = setInterval(() => void tick(), POLL_INTERVAL_MS);
    },
    [stopPolling],
  );

  // -------------------------------------------------------------------------
  // Lancement de la generation (background cote backend)
  // -------------------------------------------------------------------------
  const handleGenerate = useCallback(async () => {
    if (!sessionId) {
      toast.error("Chargez d'abord les deux cartes.");
      return;
    }
    setGenerating(true);
    setDone(false);
    setStats(null);
    setProgress(0);
    setStage("Initialisation...");
    try {
      const res = await apiClient.post<GenerateResponse>(
        "/api/evolution/generate",
        {
          session_id: sessionId,
          use_ban: useBan,
          plancher_t1: plancherT1,
          include_new: includeNew,
        },
      );
      if (!res.started) {
        setGenerating(false);
        toast.error("Le backend n'a pas demarre la generation.");
        return;
      }
      startPolling(res.session_id ?? sessionId);
    } catch (err: unknown) {
      setGenerating(false);
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Generation echouee : ${message}`);
    }
  }, [sessionId, useBan, plancherT1, includeNew, startPolling]);

  // -------------------------------------------------------------------------
  // Telechargement du GeoJSON resultat (Bearer via apiClient.download)
  // -------------------------------------------------------------------------
  const handleDownload = useCallback(() => {
    if (!sessionId) return;
    apiClient
      .download(
        `/api/evolution/download/${sessionId}`,
        `evolution_debits_${sessionId.slice(0, 8)}.geojson`,
      )
      .catch((err: Error) => toast.error(`Telechargement echoue : ${err.message}`));
  }, [sessionId]);

  // Reset complet du couple de cartes
  const clearPair = useCallback(() => {
    stopPolling();
    setFileT1(null);
    setFileT2(null);
    setSessionId(null);
    setGenerating(false);
    setDone(false);
    setStats(null);
    setProgress(0);
    setStage("");
  }, [stopPolling]);

  const canUpload = !!fileT1 && !!fileT2 && !uploading;
  const canGenerate = !!sessionId && !generating;

  // Ensure NEXT_PUBLIC_API_URL is read at least once (keeps the import used and
  // documents that the front consumes getApiBase()-prefixed endpoints).
  const apiBase = getApiBase();

  // =========================================================================
  // RENDER
  // =========================================================================
  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <NeonButton
          variant="ghost"
          onClick={() => router.push("/")}
          icon={<ArrowLeft size={14} />}
          className="text-xs"
        >
          Accueil
        </NeonButton>
        <div className="px-3 py-1 rounded-lg bg-emerald-500/10 text-emerald-300 text-xs font-bold uppercase tracking-wide">
          Evolution des debits
        </div>
      </div>

      <div className="space-y-2">
        <GradientText as="h1" className="text-2xl">
          Carte d&apos;evolution des debits
        </GradientText>
        <p className="text-sm text-slate-300">
          Comparez deux cartes de debits redressees (annee 1 = T1, annee 2 = T2,
          base topologique = T2) pour produire une carte d&apos;evolution par
          troncon. Metrique : <span className="font-mono text-emerald-300">JOr</span>{" "}
          uniquement. L&apos;evolution{" "}
          <span className="font-mono text-emerald-300">JOr (%)</span> ={" "}
          <span className="font-mono">round((T2 - T1) / T1 × 100, 2)</span>.
        </p>
      </div>

      {/* ===================================================================== */}
      {/* SECTION 1 — Upload des 2 cartes                                       */}
      {/* ===================================================================== */}
      <GlowCard glowColor="cyan">
        <div className="flex items-center gap-2 mb-5">
          <div className="w-7 h-7 rounded-lg bg-cyan/20 flex items-center justify-center text-cyan text-xs font-bold">
            1
          </div>
          <h3 className="text-sm font-semibold text-white">
            Cartes a comparer (GeoJSON)
          </h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <Calendar size={14} className="text-sky-400" />
              <span>Carte annee 1 — T1</span>
            </div>
            <DropZone
              file={fileT1}
              onFile={setFileT1}
              onClear={() => setFileT1(null)}
              accept={ACCEPT_GEOJSON}
              label="Deposez la carte de l'annee 1 (T1)"
              description=".geojson ou .json — ex 2023.geojson"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <Calendar size={14} className="text-emerald-400" />
              <span>Carte annee 2 — T2 (base)</span>
            </div>
            <DropZone
              file={fileT2}
              onFile={setFileT2}
              onClear={() => setFileT2(null)}
              accept={ACCEPT_GEOJSON}
              label="Deposez la carte de l'annee 2 (T2, base)"
              description=".geojson ou .json — ex 2024.geojson"
            />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <NeonButton
            onClick={handleUpload}
            disabled={!canUpload}
            icon={
              uploading ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Layers size={14} />
              )
            }
          >
            {uploading ? "Chargement..." : "Charger les deux cartes"}
          </NeonButton>

          {sessionId && (
            <>
              <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400">
                <CheckCircle2 size={14} />
                Session {sessionId.slice(0, 8)} prete
              </span>
              <button
                type="button"
                onClick={clearPair}
                className="text-xs text-slate-400 hover:text-slate-200 underline-offset-2 hover:underline cursor-pointer"
              >
                Reinitialiser
              </button>
            </>
          )}
        </div>
      </GlowCard>

      {/* ===================================================================== */}
      {/* SECTION 2 — Options de l'appariement                                  */}
      {/* ===================================================================== */}
      <GlowCard glowColor="violet">
        <div className="flex items-center gap-2 mb-5">
          <div className="w-7 h-7 rounded-lg bg-violet/20 flex items-center justify-center text-violet text-xs font-bold">
            2
          </div>
          <h3 className="text-sm font-semibold text-white">
            Parametres de l&apos;appariement
          </h3>
        </div>

        <div className="space-y-5">
          {/* Plancher emergent */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label
                htmlFor="evo-plancher"
                className="text-[11px] text-slate-200 flex items-center gap-1.5"
              >
                <TrendingUp size={12} className="text-violet-400" />
                Plancher T1 (garde-fou &laquo; emergent &raquo;)
              </label>
              <span className="text-[11px] text-indigo-300 font-semibold tabular-nums">
                {NF_FR.format(plancherT1)} v/j
              </span>
            </div>
            <input
              id="evo-plancher"
              type="range"
              min={0}
              max={500}
              step={10}
              value={plancherT1}
              onChange={(e) => setPlancherT1(Number(e.target.value))}
              className="w-full h-1.5 rounded-full appearance-none bg-[rgba(255,255,255,0.08)] cursor-pointer accent-indigo-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-indigo-500"
              aria-label="Plancher T1 en vehicules par jour"
            />
            <p className="text-[10px] text-slate-500">
              Un troncon dont T1 est inferieur au plancher est classe{" "}
              <span className="text-violet-300">emergent</span> : pas de
              pourcentage (JOr = null), seul le delta absolu dJOr est conserve.
              Evite les % aberrants sur des bases infimes.
            </p>
          </div>

          {/* BAN */}
          <label className="flex items-start gap-2.5 cursor-pointer group">
            <input
              type="checkbox"
              checked={useBan}
              onChange={(e) => setUseBan(e.target.checked)}
              className="mt-0.5 w-3.5 h-3.5 rounded border-white/20 bg-[rgba(15,20,40,0.6)] accent-emerald-500 cursor-pointer"
            />
            <div className="flex-1">
              <span className="text-[11px] font-medium text-slate-200 group-hover:text-emerald-300 transition-colors flex items-center gap-1.5">
                <ShieldCheck size={12} className="text-emerald-400" />
                Verification BAN (filtre de securite)
              </span>
              <p className="text-[10px] text-slate-500 mt-0.5">
                Reverse-geocoding des points milieux (api-adresse.data.gouv.fr).
                Un MISMATCH retrograde un appariement GEOM_AUTO en GEOM_VERIF ;
                BAN ne promeut jamais un rejet. Etape supplementaire (plus
                longue) mais plus fiable.
              </p>
            </div>
          </label>

          {/* include_new */}
          <label className="flex items-start gap-2.5 cursor-pointer group">
            <input
              type="checkbox"
              checked={includeNew}
              onChange={(e) => setIncludeNew(e.target.checked)}
              className="mt-0.5 w-3.5 h-3.5 rounded border-white/20 bg-[rgba(15,20,40,0.6)] accent-sky-500 cursor-pointer"
            />
            <div className="flex-1">
              <span className="text-[11px] font-medium text-slate-200 group-hover:text-sky-300 transition-colors flex items-center gap-1.5">
                <GitCompareArrows size={12} className="text-sky-400" />
                Inclure les troncons &laquo; nouveaux &raquo; (T2 seul)
              </span>
              <p className="text-[10px] text-slate-500 mt-0.5">
                Emet les troncons de la base T2 sans appariement T1 (categorie{" "}
                <span className="text-sky-300">nouveau</span>, T1/JOr/dJOr null).
                Recommande pour la completude.
              </p>
            </div>
          </label>
        </div>
      </GlowCard>

      {/* ===================================================================== */}
      {/* SECTION 3 — Generation + progression                                  */}
      {/* ===================================================================== */}
      <GlowCard glowColor="accent">
        <div className="flex items-center gap-2 mb-5">
          <div className="w-7 h-7 rounded-lg bg-accent/20 flex items-center justify-center text-accent text-xs font-bold">
            3
          </div>
          <h3 className="text-sm font-semibold text-white">
            Generation de la carte d&apos;evolution
          </h3>
        </div>

        {!sessionId && (
          <p className="text-xs text-slate-400 mb-4">
            Chargez d&apos;abord les deux cartes (Etape 1) pour activer la
            generation.
          </p>
        )}

        <NeonButton
          onClick={handleGenerate}
          disabled={!canGenerate}
          icon={
            generating ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <GitCompareArrows size={14} />
            )
          }
        >
          {generating ? "Generation en cours..." : "Generer l'evolution"}
        </NeonButton>

        {/* Progression */}
        <AnimatePresence>
          {(generating || (progress > 0 && !done)) && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 space-y-2"
            >
              <div className="flex items-center justify-between text-[11px] text-slate-300">
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin text-accent" />
                  {stage || "Traitement..."}
                </span>
                <span className="tabular-nums text-accent font-semibold">
                  {Math.round(progress)}%
                </span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-[rgba(255,255,255,0.08)] overflow-hidden">
                <div
                  className="h-full bg-accent transition-[width] duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-[10px] text-slate-500">
                Appariement N1 (cle exacte agregId) puis N2 (map-matching
                geometrique){useBan ? " puis N3 (verification BAN)" : ""}. Ce
                calcul peut prendre plusieurs minutes.
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </GlowCard>

      {/* ===================================================================== */}
      {/* RESULTS                                                               */}
      {/* ===================================================================== */}
      <AnimatePresence>
        {done && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            <NeonBorder tone="success" speed={3.2} className="overflow-hidden">
              <div className="text-center px-6 py-7 space-y-5">
                <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center mx-auto">
                  <GitCompareArrows size={28} />
                </div>

                <ShimmerText
                  as="h3"
                  variant="neon-white"
                  className="text-base font-semibold"
                >
                  Carte d&apos;evolution generee
                </ShimmerText>

                {stats && (
                  <RevealOnScroll
                    variant="scale"
                    stagger={0.06}
                    className="flex flex-wrap items-center justify-center gap-2 max-w-3xl mx-auto"
                  >
                    <StatBadge
                      tone="accent"
                      icon={<Layers />}
                      label="troncons emis"
                      value={NF_FR.format(stats.n_total ?? 0)}
                    />
                    <StatBadge
                      tone="cyan"
                      icon={<CheckCircle2 />}
                      label="apparies cle exacte"
                      value={NF_FR.format(stats.n_cle ?? 0)}
                    />
                    <StatBadge
                      tone="violet"
                      icon={<GitCompareArrows />}
                      label="apparies map-matching (auto+verif)"
                      value={NF_FR.format(
                        (stats.n_geom_auto ?? 0) + (stats.n_geom_verif ?? 0),
                      )}
                    />
                    <StatBadge
                      tone="neutral"
                      icon={<MapIcon />}
                      label="nouveaux (T2 seul)"
                      value={NF_FR.format(stats.n_non_match ?? 0)}
                    />
                    <StatBadge
                      tone="amber"
                      icon={<TrendingUp />}
                      label="evolutions significatives"
                      value={NF_FR.format(stats.n_sig ?? 0)}
                    />
                  </RevealOnScroll>
                )}

                <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
                  <MagneticButton
                    variant="primary"
                    size="lg"
                    onClick={() =>
                      sessionId &&
                      router.push(`/evolution/visualiser/${sessionId}`)
                    }
                    disabled={!sessionId}
                  >
                    <MapIcon size={16} />
                    Visualiser l&apos;evolution
                  </MagneticButton>
                  <MagneticButton
                    variant="secondary"
                    size="lg"
                    onClick={handleDownload}
                  >
                    <Download size={16} />
                    Telecharger le GeoJSON
                  </MagneticButton>
                </div>

                {apiBase && (
                  <p className="text-[10px] text-slate-600">
                    API : {apiBase || "proxy local"} /api/evolution
                  </p>
                )}
              </div>
            </NeonBorder>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
