"use client";

/**
 * useModelsList — fetches the list of models for a given training session.
 */
import { useQuery } from "@tanstack/react-query";
import { apiClient, ApiError } from "@/lib/api";
import type { ModelsListResponse } from "@/lib/types/api";

export function useModelsList(sessionId: string | null | undefined) {
  return useQuery<ModelsListResponse, ApiError>({
    queryKey: ["models-list", sessionId],
    queryFn: ({ signal }) =>
      apiClient.get<ModelsListResponse>(
        `/api/models/list?session_id=${encodeURIComponent(sessionId ?? "")}`,
        { signal }
      ),
    enabled: Boolean(sessionId),
    staleTime: 30_000,
  });
}
