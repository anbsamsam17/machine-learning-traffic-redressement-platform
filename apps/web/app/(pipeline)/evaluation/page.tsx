"use client";

import { useState, useCallback } from "react";
import { motion } from "framer-motion";
import { Download, Upload } from "lucide-react";
import { toast } from "sonner";
import { GradientText } from "@/components/ui/gradient-text";
import { GlowCard } from "@/components/ui/glow-card";
import { NeonButton } from "@/components/ui/neon-button";
import { DropZone } from "@/components/upload/drop-zone";
import {
  ModelComparison,
  type ModelResult,
} from "@/components/pipeline/model-comparison";
import { ModelDetailDrawer } from "@/components/pipeline/model-detail-drawer";
import { useAppStore } from "@/lib/store";

// Demo data
const DEMO_MODELS: ModelResult[] = [
  {
    id: "1",
    name: "MDL_128-64-32_relu",
    architecture: "128-64-32",
    activation: "relu",
    lr: 0.001,
    epochs: 500,
    trainLoss: 0.000234,
    valLoss: 0.000312,
    r2: 0.9847,
    mape: 8.2,
    gehPct: 91.3,
    isBest: true,
  },
  {
    id: "2",
    name: "MDL_64-32_relu",
    architecture: "64-32",
    activation: "relu",
    lr: 0.001,
    epochs: 500,
    trainLoss: 0.000289,
    valLoss: 0.000356,
    r2: 0.9812,
    mape: 9.1,
    gehPct: 88.7,
  },
  {
    id: "3",
    name: "MDL_128-64_tanh",
    architecture: "128-64",
    activation: "tanh",
    lr: 0.01,
    epochs: 200,
    trainLoss: 0.000345,
    valLoss: 0.000401,
    r2: 0.9756,
    mape: 10.5,
    gehPct: 85.2,
  },
  {
    id: "4",
    name: "MDL_64-32-16_relu",
    architecture: "64-32-16",
    activation: "relu",
    lr: 0.005,
    epochs: 300,
    trainLoss: 0.000412,
    valLoss: 0.000478,
    r2: 0.9701,
    mape: 11.8,
    gehPct: 82.1,
  },
  {
    id: "5",
    name: "MDL_32-16_tanh",
    architecture: "32-16",
    activation: "tanh",
    lr: 0.01,
    epochs: 200,
    trainLoss: 0.000567,
    valLoss: 0.000623,
    r2: 0.9589,
    mape: 14.2,
    gehPct: 76.4,
  },
];

export default function EvaluationPage() {
  const { mode } = useAppStore();
  const [validationFile, setValidationFile] = useState<File | null>(null);
  const [models] = useState<ModelResult[]>(DEMO_MODELS);
  const [selectedModel, setSelectedModel] = useState<ModelResult | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleView = useCallback((model: ModelResult) => {
    setSelectedModel(model);
    setDrawerOpen(true);
  }, []);

  const handleSelect = useCallback((model: ModelResult) => {
    toast.success(`Modele "${model.name}" selectionne comme meilleur modele`);
  }, []);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <GradientText as="h2" className="text-2xl">
          Evaluation
        </GradientText>
        <p className="text-sm text-muted">
          Comparez les modeles {mode === "pl" ? "PL" : "TV"} entraines,
          consultez les metriques detaillees et selectionnez le meilleur.
        </p>
      </div>

      {/* Validation file upload */}
      <GlowCard>
        <div className="flex items-center gap-2 mb-4">
          <Upload size={18} className="text-accent" />
          <h3 className="text-sm font-semibold text-foreground">
            Fichier de validation (optionnel)
          </h3>
        </div>
        <DropZone
          file={validationFile}
          onFile={setValidationFile}
          onClear={() => setValidationFile(null)}
          label="Fichier de validation externe"
          description="GeoJSON ou CSV avec donnees de comptage"
        />
      </GlowCard>

      {/* Model comparison table */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">
            Comparaison des modeles
          </h3>
          <NeonButton
            variant="secondary"
            icon={<Download size={14} />}
            className="text-xs"
          >
            Telecharger le rapport ZIP
          </NeonButton>
        </div>
        <ModelComparison
          models={models}
          onView={handleView}
          onSelect={handleSelect}
        />
      </div>

      {/* Drawer */}
      <ModelDetailDrawer
        model={selectedModel}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
