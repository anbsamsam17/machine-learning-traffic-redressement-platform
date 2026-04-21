/**
 * API base URL — resolved at runtime on the client.
 * In dev: uses Next.js proxy (/api/...)
 * In prod: uses the full Railway API URL from NEXT_PUBLIC_API_URL
 */
export function getApiBase(): string {
  // NEXT_PUBLIC_ vars are inlined at build time by Next.js
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl) return envUrl;
  // Fallback: dev mode, use relative path (Next.js proxy)
  return "";
}

/**
 * Build full API URL. In dev returns "/api/...", in prod returns "https://api.railway.app/api/..."
 */
export function apiUrl(path: string): string {
  const base = getApiBase();
  // If path already starts with /api, use it directly
  if (path.startsWith("/api")) return `${base}${path}`;
  // Otherwise prepend /api
  return `${base}/api${path.startsWith("/") ? path : `/${path}`}`;
}
