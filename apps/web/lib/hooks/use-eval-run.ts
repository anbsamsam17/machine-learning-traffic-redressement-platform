"use client";

/**
 * useEvalRun — mutation that triggers /api/evaluation/run.
 */
import { useMutation } from "@tanstack/react-query";
import { apiClient, ApiError } from "@/lib/api";
import type { EvalRunResponse } from "@/lib/types/api";

export interface EvalRunPayload {
  session_id: string;
  model_name: string;
  model_dir?: string;
  filter_flag_comptage?: boolean;
  column_mapping?: Record<string, string>;
  year_column_name?: string | null;
  year_value_mapping?: Record<string, number> | null;
}

export function useEvalRun() {
  return useMutation<EvalRunResponse, ApiError, EvalRunPayload>({
    mutationFn: (payload) =>
      apiClient.post<EvalRunResponse>("/api/evaluation/run", payload, {
        timeoutMs: 5 * 60_000,
      }),
  });
}
