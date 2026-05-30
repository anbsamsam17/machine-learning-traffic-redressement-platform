/**
 * use-training-cancel — Bug 2 (T1).
 *
 * Helper hook that POSTs /api/training/cancel/{taskId} then polls
 * /api/training/status/{taskId} until the backend confirms the cancel
 * (status === "cancelled" / "failed") or a timeout is reached.
 *
 * The training page uses this so the user sees a real "Annule" state
 * instead of a frozen "Annulation demandee..." progress bar.
 */

"use client";

import { useCallback, useRef } from "react";
import { apiUrl } from "@/lib/api-url";
import { fetchWithAuth } from "@/lib/auth";

interface TrainingStatusPayload {
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "cancelling";
}

export interface UseTrainingCancelOptions {
  /** Called once when the cancel request has been accepted by the backend. */
  onRequested?: () => void;
  /** Called when the backend confirms status === "cancelled". */
  onConfirmed?: () => void;
  /** Called when the backend never confirmed before the timeout elapsed. */
  onTimeout?: () => void;
  /** Called on POST/network failure. */
  onError?: (message: string) => void;
  /** Polling interval in ms. Defaults to 500ms. */
  pollIntervalMs?: number;
  /** Max wait time in ms before falling back to onTimeout. Defaults to 10000ms. */
  timeoutMs?: number;
}

export interface UseTrainingCancelResult {
  /** Trigger cancel + start polling. Safe to call multiple times (idempotent). */
  cancel: (taskId: string) => Promise<void>;
  /** Stop any in-flight polling (e.g. on unmount). */
  stop: () => void;
}

export function useTrainingCancel(
  options: UseTrainingCancelOptions = {}
): UseTrainingCancelResult {
  const {
    onRequested,
    onConfirmed,
    onTimeout,
    onError,
    pollIntervalMs = 500,
    timeoutMs = 10_000,
  } = options;

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guard against concurrent cancel() calls on the same task.
  const inFlightRef = useRef<string | null>(null);

  const stop = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    inFlightRef.current = null;
  }, []);

  const cancel = useCallback(
    async (taskId: string) => {
      if (!taskId) return;
      if (inFlightRef.current === taskId) return;
      inFlightRef.current = taskId;

      try {
        const res = await fetchWithAuth(apiUrl(`/api/training/cancel/${taskId}`), {
          method: "POST",
        });
        if (!res.ok && res.status !== 404) {
          // 404 can mean "already gone" — treat as success-ish.
          const detail = await res
            .json()
            .then((d: { detail?: string }) => d.detail)
            .catch(() => null);
          throw new Error(detail || `Cancel failed: ${res.status}`);
        }
      } catch (err) {
        inFlightRef.current = null;
        const msg = err instanceof Error ? err.message : "Erreur inconnue";
        onError?.(msg);
        return;
      }

      onRequested?.();

      // Start polling status until confirmed cancelled / failed, or timeout.
      stop();

      timeoutRef.current = setTimeout(() => {
        stop();
        onTimeout?.();
      }, timeoutMs);

      pollRef.current = setInterval(async () => {
        try {
          const res = await fetchWithAuth(apiUrl(`/api/training/status/${taskId}`));
          if (!res.ok) return;
          const data = (await res.json()) as TrainingStatusPayload;
          if (
            data.status === "cancelled" ||
            data.status === "failed" ||
            data.status === "completed"
          ) {
            stop();
            onConfirmed?.();
          }
        } catch {
          // Network blip — keep polling until timeout.
        }
      }, pollIntervalMs);
    },
    [onConfirmed, onError, onRequested, onTimeout, pollIntervalMs, stop, timeoutMs]
  );

  return { cancel, stop };
}
