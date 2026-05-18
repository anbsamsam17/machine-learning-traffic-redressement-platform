"use client";

/**
 * useTrainingStatus — TanStack Query hook polling /api/training/status/:taskId.
 *
 * Polling cadence is adaptive: 1s while the worker is still in early epochs,
 * then 2s / 5s / 10s as the run matures. When the status reaches "completed"
 * or "failed" the query stops polling.
 *
 * The hook stops emitting refetches when `taskId` is null/undefined.
 */
import { useQuery, type UseQueryOptions } from "@tanstack/react-query";
import { apiClient, ApiError } from "@/lib/api";
import type { TrainingStatus } from "@/lib/types/api";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

function pickInterval(status: TrainingStatus | undefined): number | false {
  if (!status) return 1_000;
  if (TERMINAL_STATUSES.has(status.status)) return false;
  // Quick polling at the start, then back off as the run matures.
  const epoch = status.current_epoch ?? 0;
  if (epoch < 50) return 1_000;
  if (epoch < 200) return 2_000;
  if (epoch < 1000) return 5_000;
  return 10_000;
}

interface UseTrainingStatusOptions
  extends Omit<
    UseQueryOptions<TrainingStatus, ApiError>,
    "queryKey" | "queryFn" | "refetchInterval"
  > {
  /** Disable polling externally (e.g. when the page is hidden). */
  enabled?: boolean;
}

export function useTrainingStatus(
  taskId: string | null | undefined,
  opts: UseTrainingStatusOptions = {}
) {
  return useQuery<TrainingStatus, ApiError>({
    queryKey: ["training-status", taskId],
    queryFn: ({ signal }) =>
      apiClient.get<TrainingStatus>(`/api/training/status/${taskId}`, {
        signal,
        timeoutMs: 15_000,
      }),
    enabled: Boolean(taskId) && (opts.enabled ?? true),
    refetchInterval: (q) => pickInterval(q.state.data),
    refetchIntervalInBackground: true,
    staleTime: 0,
    ...opts,
  });
}
