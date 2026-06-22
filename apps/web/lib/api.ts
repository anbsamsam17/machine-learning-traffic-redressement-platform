/**
 * apiClient: client HTTP préféré pour les nouveaux endpoints.
 *
 * Centralized typed API client.
 *
 * - Injects `Authorization: Bearer ${token}` on every request.
 * - Handles 401 globally by clearing the token and redirecting to /login.
 * - Generic JSON helpers (get/post/postForm).
 * - Backwards-compatible top-level helpers `fetchJSON` / `uploadFile`
 *   are kept so existing call sites keep working while migration completes.
 */
import { getApiBase, apiUrl } from "./api-url";
import { getToken, handleSessionExpired, shouldHandle401 } from "./auth";

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

/**
 * Extract a human-readable error message from a parsed FastAPI error body.
 *
 * FastAPI returns `{ detail: string }` for plain HTTPException errors,
 * but `{ detail: Array<{loc, msg, type}> }` for Pydantic 422 validation
 * errors. Passing the array directly to React or `new Error()` results
 * in either a "Objects are not valid as a React child" crash or an
 * unhelpful "[object Object]" message. This helper normalizes both
 * shapes into a single string safe to render.
 */
export function parseApiError(
  data: unknown,
  fallback = "Erreur inconnue"
): string {
  if (data == null) return fallback;
  if (typeof data === "string") return data;
  if (typeof data !== "object") return String(data);

  const detail = (data as { detail?: unknown }).detail;
  if (detail == null) {
    const message = (data as { message?: unknown }).message;
    return typeof message === "string" ? message : fallback;
  }
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Pydantic validation error: Array<{loc, msg, type}>
    const parts = detail.map((item) => {
      if (item && typeof item === "object") {
        const obj = item as { loc?: unknown; msg?: unknown };
        const loc = Array.isArray(obj.loc)
          ? obj.loc.filter((p) => p !== "body").join(".")
          : "";
        const msg = typeof obj.msg === "string" ? obj.msg : JSON.stringify(item);
        return loc ? `${loc}: ${msg}` : msg;
      }
      return String(item);
    });
    return parts.join(" ; ") || fallback;
  }
  if (typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return String(detail);
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
  if (res.status === 401 && shouldHandle401(res.url)) {
    // Centralized handler: clears the token, shows a toast and
    // redirects to /login?reason=expired&redirect=<current>.
    handleSessionExpired();
  }
  if (!res.ok) {
    let detail = res.statusText || "Unknown error";
    try {
      const ct = res.headers.get("content-type") ?? "";
      if (ct.includes("application/json")) {
        const j = await res.json();
        // parseApiError handles both string `detail` (HTTPException) and
        // array `detail` (Pydantic 422 validation errors) safely.
        detail = parseApiError(j, detail);
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
        fetch(fullUrl(path), {
          method: "GET",
          headers: buildHeaders(),
          credentials: "include",
          signal,
        }).then(handle<T>),
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
          credentials: "include",
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
          credentials: "include",
          body: form,
          signal,
        }).then(handle<T>),
      opts.signal,
      opts.timeoutMs ?? 5 * 60_000 // 5 min for uploads
    );
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
