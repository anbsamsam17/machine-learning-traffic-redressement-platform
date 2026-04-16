"use client";

import { create } from "zustand";

export type AppMode = "tv" | "pl" | "carte" | "compteurs" | null;

export interface PipelineStep {
  id: string;
  label: string;
  path: string;
}

export const PIPELINE_STEPS: PipelineStep[] = [
  { id: "donnees", label: "Donnees", path: "/donnees" },
  { id: "config", label: "Configuration", path: "/config" },
  { id: "training", label: "Entrainement", path: "/training" },
  { id: "evaluation", label: "Evaluation", path: "/evaluation" },
  { id: "extrapolation", label: "Extrapolation", path: "/extrapolation" },
];

interface AppState {
  mode: AppMode;
  currentStep: number;
  sessionId: string | null;
  taskId: string | null;
  territory: string | null;
  fileName: string | null;
  outputDir: string | null;
  trainingConfig: Record<string, unknown> | null;

  setMode: (mode: AppMode) => void;
  setTerritory: (territory: string) => void;
  setFileName: (name: string) => void;
  setSessionId: (id: string) => void;
  setTaskId: (id: string) => void;
  setOutputDir: (dir: string) => void;
  setTrainingConfig: (config: Record<string, unknown>) => void;
  nextStep: () => void;
  prevStep: () => void;
  goToStep: (step: number) => void;
  reset: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  mode: null,
  currentStep: 0,
  sessionId: null,
  taskId: null,
  territory: null,
  fileName: null,
  outputDir: null,
  trainingConfig: null,

  setMode: (mode) => set({ mode }),
  setTerritory: (territory) => set({ territory }),
  setFileName: (name) => set({ fileName: name }),
  setSessionId: (id) => set({ sessionId: id }),
  setTaskId: (id) => set({ taskId: id }),
  setOutputDir: (dir) => set({ outputDir: dir }),
  setTrainingConfig: (config) => set({ trainingConfig: config }),
  nextStep: () =>
    set((s) => ({
      currentStep: Math.min(s.currentStep + 1, PIPELINE_STEPS.length - 1),
    })),
  prevStep: () =>
    set((s) => ({ currentStep: Math.max(s.currentStep - 1, 0) })),
  goToStep: (step) => set({ currentStep: step }),
  reset: () =>
    set({
      mode: null,
      currentStep: 0,
      sessionId: null,
      taskId: null,
      territory: null,
      fileName: null,
      outputDir: null,
      trainingConfig: null,
    }),
}));
