/**
 * Centralized typed API client.
 *
 * - Injects `Authorization: Bearer ${token}` on every request.
 * - Handles 401 globally by clearing the token and redirecting to /login.
 * - Generic JSON helpers (get/post/postForm) + SSE stream helper.
 * - Backwards-compatible top-level helpers `fetchJSON` / `uploadFile`
 *   are kept so existing call sites keep working while migration completes.
 */
import { getApiBase, apiUrl } from "./api-url";
import { getToken, removeToken } from "./auth";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string, message?: string) {
    super(message ?? `API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface BaseOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

function buildHeaders(extra?: HeadersInit, withJson = true): Headers {
  const headers = new Headers(extra);
  if (withJson && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

function fullUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  if (path.startsWith("/api")) return `${getApiBase()}${path}`;
  return apiUrl(path);
}

async function handle<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    // Don't redirect auth endpoints (login/register/me) — let caller handle.
    const isAuth = res.url.includes("/api/auth/");
    if (!isAuth && typeof window !== "undefined") {
      removeToken();
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    let detail = res.statusText || "Unknown error";
    try {
      const ct = res.headers.get("content-type") ?? "";
      if (ct.includes("application/json")) {
        const j = (await res.json()) as { detail?: string; message?: string };
        detail = j.detail ?? j.message ?? detail;
      } else {
        detail = await res.text();
      }
    } catch {
      /* swallow */
    }
    throw new ApiError(res.status, detail);
  }
  // 204 / empty body
  const ct = res.headers.get("content-type") ?? "";
  if (res.status === 204 || !ct.includes("application/json")) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

async function withTimeout<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  outerSignal: AbortSignal | undefined,
  timeoutMs: number
): Promise<T> {
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  outerSignal?.addEventListener("abort", onAbort);
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fn(ctrl.signal);
  } finally {
    clearTimeout(t);
    outerSignal?.removeEventListener("abort", onAbort);
  }
}

export const apiClient = {
  async get<T>(path: string, opts: BaseOptions = {}): Promise<T> {
    return withTimeout(
      (signal) =>
        fetch(fullUrl(path), { method: "GET", headers: buildHeaders(), signal }).then(handle<T>),
      opts.signal,
      opts.timeoutMs ?? 30_000
    );
  },

  async post<T, B = unknown>(
    path: string,
    body: B,
    opts: BaseOptions = {}
  ): Promise<T> {
    return withTimeout(
      (signal) =>
        fetch(fullUrl(path), {
          method: "POST",
          headers: buildHeaders(),
          body: body === undefined ? undefined : JSON.stringify(body),
          signal,
        }).then(handle<T>),
      opts.signal,
      opts.timeoutMs ?? 30_000
    );
  },

  async postForm<T>(
    path: string,
    form: FormData,
    opts: BaseOptions = {}
  ): Promise<T> {
    return withTimeout(
      (signal) =>
        fetch(fullUrl(path), {
          method: "POST",
          headers: buildHeaders(undefined, false), // let browser set boundary
          body: form,
          signal,
        }).then(handle<T>),
      opts.signal,
      opts.timeoutMs ?? 5 * 60_000 // 5 min for uploads
    );
  },

  /** Open an SSE stream. Caller is responsible for closing the returned EventSource. */
  stream(
    path: string,
    handlers: {
      onMessage?: (data: unknown) => void;
      onError?: (e: Event) => void;
      onOpen?: () => void;
    }
  ): EventSource {
    const url = fullUrl(path);
    const es = new EventSource(url);
    if (handlers.onOpen) es.onopen = handlers.onOpen;
    es.onmessage = (event) => {
      if (!handlers.onMessage) return;
      try {
        handlers.onMessage(JSON.parse(event.data));
      } catch {
        handlers.onMessage(event.data);
      }
    };
    es.onerror = (e) => handlers.onError?.(e);
    return es;
  },

  /** Trigger a file download in the browser. Adds auth via temp link. */
  async download(path: string, filename: string): Promise<void> {
    const res = await fetch(fullUrl(path), { headers: buildHeaders(undefined, false) });
    if (!res.ok) throw new ApiError(res.status, await res.text().catch(() => "download failed"));
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

/* ─── Legacy compatibility shims (used by existing call sites) ────────── */

export async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const method = (options?.method ?? "GET").toUpperCase();
  const url = path.startsWith("http") || path.startsWith("/api") ? path : `/api${path.startsWith("/") ? path : `/${path}`}`;
  if (method === "GET") return apiClient.get<T>(url);
  if (method === "POST") {
    const body = options?.body ? JSON.parse(String(options.body)) : undefined;
    return apiClient.post<T>(url, body);
  }
  // Fallback: pass-through with auth
  const res = await fetch(fullUrl(url), {
    ...options,
    headers: buildHeaders(options?.headers),
  });
  return handle<T>(res);
}

export async function uploadFile<T = unknown>(
  path: string,
  file: File,
  extraFields?: Record<string, string>
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  if (extraFields) {
    for (const [k, v] of Object.entries(extraFields)) form.append(k, v);
  }
  return apiClient.postForm<T>(path, form);
}

export function streamSSE(
  path: string,
  onMessage: (data: Record<string, unknown>) => void,
  onError?: (err: Event) => void
): EventSource {
  return apiClient.stream(path, {
    onMessage: (d) => onMessage(d as Record<string, unknown>),
    onError,
  });
}
