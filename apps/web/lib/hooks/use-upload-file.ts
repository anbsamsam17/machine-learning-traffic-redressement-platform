"use client";

/**
 * useUploadFile — mutation that POSTs a single file to /api/upload (or any
 * compatible multipart endpoint) along with optional string fields.
 */
import { useMutation } from "@tanstack/react-query";
import { apiClient, ApiError } from "@/lib/api";

export interface UploadFilePayload<TExtra extends Record<string, string> = Record<string, string>> {
  file: File;
  path?: string;
  extra?: TExtra;
}

export function useUploadFile<TResp = unknown>() {
  return useMutation<TResp, ApiError, UploadFilePayload>({
    mutationFn: ({ file, path = "/api/upload", extra }) => {
      const form = new FormData();
      form.append("file", file);
      if (extra) {
        for (const [k, v] of Object.entries(extra)) {
          form.append(k, v);
        }
      }
      return apiClient.postForm<TResp>(path, form);
    },
  });
}
