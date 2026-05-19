"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { apiUrl } from "./api-url";
import { fetchWithAuth } from "./auth";

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
];

/** Shape returned by the backend GET /api/sessions/current endpoint. */
export interface BackendSessionState {
  session_id: string;
  mode: string; // "tv" | "pl"
  step:
    | "upload"
    | "mapping"
    | "preview"
    | "config"
    | "training"
    | "evaluation";
  file_name: string | null;
  rows: number | null;
  columns_count: number | null;
  mapping_validated: boolean;
  training_task_id: string | null;
  output_dir: string | null;
}

/**
 * Map a backend "step" name to the index of the stepper we want the
 * user to land on. The "upload" / "mapping" / "preview" sub-steps all
 * live inside /donnees (step 0), so they collapse to 0.
 */
function backendStepToStepperIndex(step: BackendSessionState["step"]): number {
  switch (step) {
    case "config":
      return 1;
    case "training":
      return 2;
    case "evaluation":
      return 3;
    default:
      return 0;
  }
}

interface AppState {
  mode: AppMode;
  currentStep: number;
  sessionId: string | null;
  taskId: string | null;
  fileName: string | null;
  outputDir: string | null;
  trainingConfig: Record<string, unknown> | null;

  setMode: (mode: AppMode) => void;
  setFileName: (name: string) => void;
  setSessionId: (id: string) => void;
  setTaskId: (id: string | null) => void;
  setOutputDir: (dir: string) => void;
  setTrainingConfig: (config: Record<string, unknown>) => void;
  nextStep: () => void;
  prevStep: () => void;
  goToStep: (step: number) => void;
  reset: () => void;
  /**
   * Pull the user's active session from the backend and hydrate the store.
   * Idempotent — safe to call on every page mount. Returns true if a session
   * was restored, false otherwise (no auth, no session, or fetch failure).
   */
  restoreFromBackend: () => Promise<boolean>;
}

const noopStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
};

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      mode: null,
      currentStep: 0,
      sessionId: null,
      taskId: null,
      fileName: null,
      outputDir: null,
      trainingConfig: null,

      setMode: (mode) => set({ mode }),
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
          fileName: null,
          outputDir: null,
          trainingConfig: null,
        }),
      restoreFromBackend: async () => {
        if (typeof window === "undefined") return false;
        try {
          const res = await fetchWithAuth(apiUrl("/api/sessions/current"));
          if (res.status === 404) return false;
          if (!res.ok) return false;
          const data = (await res.json()) as BackendSessionState;
          if (!data || !data.session_id) return false;

          const currentStep = backendStepToStepperIndex(data.step);
          const normalizedMode = (data.mode === "pl" ? "pl" : "tv") as AppMode;

          set((s) => ({
            // Always trust the backend session id over whatever is in sessionStorage
            sessionId: data.session_id,
            // Only fill mode if not already chosen by the user (e.g. carte/compteurs)
            mode: s.mode ?? normalizedMode,
            // Restore filename if we have one and the local store is empty
            fileName: s.fileName ?? data.file_name,
            taskId: s.taskId ?? data.training_task_id,
            outputDir: s.outputDir ?? data.output_dir,
            // Don't downgrade the stepper if the user has already navigated
            // further than what the backend reports.
            currentStep: Math.max(s.currentStep, currentStep),
          }));
          return true;
        } catch {
          return false;
        }
      },
    }),
    {
      name: "mdl-pipeline-store",
      // localStorage so a long-running training survives a tab close/reopen.
      storage: createJSONStorage(() =>
        typeof window !== "undefined" ? localStorage : noopStorage
      ),
    }
  )
);
