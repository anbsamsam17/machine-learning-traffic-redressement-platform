"use client";

import { useState, useMemo } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Layers, Zap, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { TagInput } from "@/components/ui/tag-input";
import { NeonButton } from "@/components/ui/neon-button";
import type { AppMode } from "@/lib/store";

const configSchema = z.object({
  inputColumns: z.array(z.string()),
  hiddenLayers: z.array(z.string()).min(1, "Au moins une architecture"),
  activations: z.array(z.string()).min(1, "Au moins une activation"),
  learningRates: z.array(z.string()).min(1, "Au moins un learning rate"),
  epochs: z.array(z.string()).min(1, "Au moins un nombre d'epochs"),
  batchSizes: z.array(z.string()).min(1, "Au moins un batch size"),
  testSplit: z.number().min(0.05).max(0.5),
  seed: z.number().int().positive(),
});

type ConfigValues = z.infer<typeof configSchema>;

const ALL_INPUT_COLUMNS = [
  "VitesseMoy", "VitesseRef", "NbVoies", "Capacite", "Longueur",
  "ClasseRoute", "TypeZone", "TxPen", "TMJAFCDTV", "TMJAFCDPL",
  "DebitHoraire", "TxPoids", "Seuil", "Rampe", "Sinuosite",
  "Largeur", "MedianeSeparee", "AccesBorde", "InterDist",
];

const DEFAULT_TV: ConfigValues = {
  inputColumns: ALL_INPUT_COLUMNS.slice(0, 10),
  hiddenLayers: ["64-32", "128-64", "128-64-32"],
  activations: ["relu", "tanh"],
  learningRates: ["0.001", "0.01"],
  epochs: ["200", "500"],
  batchSizes: ["32", "64"],
  testSplit: 0.2,
  seed: 1750,
};

const DEFAULT_PL: ConfigValues = {
  inputColumns: ALL_INPUT_COLUMNS.slice(0, 8),
  hiddenLayers: ["32-16", "64-32", "64-32-16"],
  activations: ["relu"],
  learningRates: ["0.001", "0.005"],
  epochs: ["300", "500"],
  batchSizes: ["32"],
  testSplit: 0.2,
  seed: 1750,
};

interface ConfigFormProps {
  mode: AppMode;
  onSubmit: (values: ConfigValues) => void;
}

function AccordionSection({
  title,
  icon,
  children,
  defaultOpen = false,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="glass-light overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-sm font-medium text-foreground hover:bg-surface-light/50 transition-colors"
      >
        <span className="flex items-center gap-2">
          {icon}
          {title}
        </span>
        <motion.div animate={{ rotate: open ? 180 : 0 }}>
          <ChevronDown size={16} className="text-muted" />
        </motion.div>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function ConfigForm({ mode, onSubmit }: ConfigFormProps) {
  const defaults = mode === "pl" ? DEFAULT_PL : DEFAULT_TV;

  const { control, handleSubmit, watch } = useForm<ConfigValues>({
    resolver: zodResolver(configSchema),
    defaultValues: defaults,
  });

  const hiddenLayers = watch("hiddenLayers");
  const activations = watch("activations");
  const learningRates = watch("learningRates");
  const epochs = watch("epochs");
  const batchSizes = watch("batchSizes");

  const combinationsCount = useMemo(() => {
    return (
      Math.max(hiddenLayers.length, 1) *
      Math.max(activations.length, 1) *
      Math.max(learningRates.length, 1) *
      Math.max(epochs.length, 1) *
      Math.max(batchSizes.length, 1)
    );
  }, [hiddenLayers, activations, learningRates, epochs, batchSizes]);

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      {/* Colonnes d'entree */}
      <AccordionSection
        title="Colonnes d'entree"
        icon={<Layers size={16} className="text-accent" />}
        defaultOpen
      >
        <Controller
          name="inputColumns"
          control={control}
          render={({ field }) => (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {ALL_INPUT_COLUMNS.map((col) => {
                  const selected = field.value.includes(col);
                  return (
                    <button
                      key={col}
                      type="button"
                      onClick={() => {
                        if (selected) {
                          field.onChange(
                            field.value.filter((c: string) => c !== col)
                          );
                        } else {
                          field.onChange([...field.value, col]);
                        }
                      }}
                      className={cn(
                        "px-2.5 py-1 rounded-md text-xs font-medium border transition-all",
                        selected
                          ? "bg-accent/15 text-accent border-accent/30"
                          : "bg-surface text-muted border-border hover:border-accent/20"
                      )}
                    >
                      {col}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-muted">
                {field.value.length} colonnes selectionnees
              </p>
            </div>
          )}
        />
      </AccordionSection>

      {/* Grid Search */}
      <AccordionSection
        title="Grid Search"
        icon={<Settings2 size={16} className="text-cyan" />}
        defaultOpen
      >
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted mb-1 block">
              Architectures (ex: 64-32)
            </label>
            <Controller
              name="hiddenLayers"
              control={control}
              render={({ field }) => (
                <TagInput
                  values={field.value}
                  onChange={field.onChange}
                  placeholder="Ex: 128-64-32"
                />
              )}
            />
          </div>
          <div>
            <label className="text-xs text-muted mb-1 block">Activations</label>
            <Controller
              name="activations"
              control={control}
              render={({ field }) => (
                <TagInput
                  values={field.value}
                  onChange={field.onChange}
                  placeholder="relu, tanh, sigmoid..."
                />
              )}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted mb-1 block">
                Learning Rates
              </label>
              <Controller
                name="learningRates"
                control={control}
                render={({ field }) => (
                  <TagInput
                    values={field.value}
                    onChange={field.onChange}
                    placeholder="0.001, 0.01..."
                  />
                )}
              />
            </div>
            <div>
              <label className="text-xs text-muted mb-1 block">Epochs</label>
              <Controller
                name="epochs"
                control={control}
                render={({ field }) => (
                  <TagInput
                    values={field.value}
                    onChange={field.onChange}
                    placeholder="200, 500..."
                  />
                )}
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted mb-1 block">Batch Sizes</label>
            <Controller
              name="batchSizes"
              control={control}
              render={({ field }) => (
                <TagInput
                  values={field.value}
                  onChange={field.onChange}
                  placeholder="32, 64..."
                />
              )}
            />
          </div>
        </div>
      </AccordionSection>

      {/* Parametres generaux */}
      <AccordionSection
        title="Parametres generaux"
        icon={<Zap size={16} className="text-violet" />}
      >
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-muted mb-1 block">
              Test Split
            </label>
            <Controller
              name="testSplit"
              control={control}
              render={({ field }) => (
                <input
                  type="number"
                  step={0.05}
                  min={0.05}
                  max={0.5}
                  value={field.value}
                  onChange={(e) => field.onChange(parseFloat(e.target.value))}
                  className="w-full px-3 py-2 text-sm bg-surface border border-border rounded-lg text-foreground outline-none focus:border-accent/40"
                />
              )}
            />
          </div>
          <div>
            <label className="text-xs text-muted mb-1 block">Seed</label>
            <Controller
              name="seed"
              control={control}
              render={({ field }) => (
                <input
                  type="number"
                  value={field.value}
                  onChange={(e) => field.onChange(parseInt(e.target.value))}
                  className="w-full px-3 py-2 text-sm bg-surface border border-border rounded-lg text-foreground outline-none focus:border-accent/40"
                />
              )}
            />
          </div>
        </div>
      </AccordionSection>

      {/* Footer */}
      <div className="flex items-center justify-between pt-2">
        <div className="glass-light px-4 py-2 rounded-lg">
          <span className="text-xs text-muted">Combinaisons : </span>
          <span className="text-sm font-bold text-accent">
            {combinationsCount}
          </span>
        </div>
        <NeonButton type="submit" icon={<Zap size={16} />}>
          Lancer l&apos;entrainement
        </NeonButton>
      </div>
    </form>
  );
}
