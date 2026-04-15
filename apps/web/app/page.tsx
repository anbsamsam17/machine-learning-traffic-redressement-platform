"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Car, Truck, Map, CircleDot, Sparkles } from "lucide-react";
import { AuroraBg } from "@/components/backgrounds/aurora-bg";
import { GradientText } from "@/components/ui/gradient-text";
import { ModeCard } from "@/components/pipeline/mode-card";
import { useAppStore } from "@/lib/store";

export default function HomePage() {
  const router = useRouter();
  const setMode = useAppStore((s) => s.setMode);

  function handleMode(mode: "tv" | "pl" | "carte" | "compteurs") {
    setMode(mode);
    if (mode === "carte") {
      router.push("/carte");
    } else if (mode === "compteurs") {
      router.push("/compteurs");
    } else {
      router.push("/donnees");
    }
  }

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <AuroraBg />

      <div className="relative z-10 w-full max-w-3xl mx-auto text-center space-y-10">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="space-y-4"
        >
          <div className="flex items-center justify-center gap-2 mb-2">
            <Sparkles size={20} className="text-accent" />
            <span className="text-xs font-medium text-muted uppercase tracking-widest">
              MDL Redressement Tool
            </span>
          </div>
          <GradientText as="h1" className="text-4xl sm:text-5xl lg:text-6xl">
            Modelisation de Redressement
          </GradientText>
          <p className="text-muted text-sm sm:text-base max-w-lg mx-auto leading-relaxed">
            Pipeline complet de redressement FCD : import de donnees,
            entrainement grid search, evaluation multi-modeles et generation de
            cartes de debits.
          </p>
        </motion.div>

        {/* Mode cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <ModeCard
            title="Modele TV"
            description="Entrainement et evaluation du modele de redressement pour les vehicules legers (Tous Vehicules)."
            icon={<Car size={28} />}
            glowColor="accent"
            onClick={() => handleMode("tv")}
            delay={0.1}
          />
          <ModeCard
            title="Modele PL"
            description="Entrainement et evaluation du modele de redressement pour les Poids Lourds."
            icon={<Truck size={28} />}
            glowColor="violet"
            onClick={() => handleMode("pl")}
            delay={0.2}
          />
          <ModeCard
            title="Carte de Debits"
            description="Generation de cartes geographiques avec les debits redresses sur le reseau routier."
            icon={<Map size={28} />}
            glowColor="cyan"
            onClick={() => handleMode("carte")}
            delay={0.3}
          />
          <ModeCard
            title="Boucles de Comptage"
            description="Generation des boucles de comptage virtuelles a partir des modeles entraines."
            icon={<CircleDot size={28} />}
            glowColor="accent"
            onClick={() => handleMode("compteurs")}
            delay={0.4}
          />
        </div>

        {/* Footer note */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="text-xs text-muted/60"
        >
          Aucune donnee n&apos;est stockee en dehors de votre machine. Tous les
          traitements s&apos;effectuent localement.
        </motion.p>
      </div>
    </div>
  );
}
