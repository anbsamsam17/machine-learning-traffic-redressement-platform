/**
 * Auth helpers — token management.
 *
 * `fetchWithAuth` is kept as a thin compat shim around the new typed
 * apiClient (lib/api.ts). Prefer apiClient.* for new code.
 */

import { getApiBase } from "./api-url";

const TOKEN_KEY = "mdl_access_token";

// Module-level guard to avoid firing the "session expired" UX multiple
// times if several concurrent requests fail with 401 simultaneously
// (a common case when a page mounts and dispatches 3-4 fetches in parallel
// while the token has just expired).
let sessionExpiredHandled = false;

/**
 * Centralized handler invoked whenever a non-auth API call returns 401.
 * - Clears the access token (localStorage + cookie).
 * - Shows a toast notifying the user that the session has expired.
 * - Redirects to /login with `reason=expired` and the previous URL preserved
 *   in `redirect` so the user can resume after re-auth.
 *
 * Safe under SSR (no-op when `window` is undefined).
 * Safe under concurrent 401s (idempotent: only the first call triggers UX).
 */
export function handleSessionExpired(): void {
  if (typeof window === "undefined") return;
  if (sessionExpiredHandled) return;
  sessionExpiredHandled = true;

  // 1. Drop the local token immediately so subsequent in-flight calls
  //    do not re-send a dead Authorization header.
  removeToken();

  // 2. Toast (dynamic import so this module stays SSR-safe and we avoid
  //    pulling sonner into bundles that never need it).
  void import("sonner")
    .then(({ toast }) => {
      toast.error("Session expirée — reconnexion nécessaire", {
        duration: 4000,
      });
    })
    .catch(() => {
      // Sonner failed to load — fall through to the redirect anyway.
    });

  // 3. Redirect after a short delay so the toast has a chance to render.
  //    We use window.location.href (not next/router) because this helper
  //    runs outside React.
  const current = window.location.pathname + window.location.search;
  const target = `/login?reason=expired&redirect=${encodeURIComponent(current)}`;
  setTimeout(() => {
    window.location.href = target;
  }, 800);
}

/** Returns true when a 401 from this URL should trigger the session-expired flow. */
export function shouldHandle401(url: string): boolean {
  // Never intercept the auth endpoints themselves — otherwise a failed
  // login would redirect the user back to /login in a loop and a refresh
  // 401 would short-circuit the recovery path.
  if (url.includes("/api/auth/login")) return false;
  if (url.includes("/api/auth/refresh")) return false;
  if (url.includes("/api/auth/register")) return false;
  return true;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
  // Also set a cookie so the Next.js Edge middleware can read it
  document.cookie = `${TOKEN_KEY}=${token}; path=/; max-age=${60 * 60 * 24}; SameSite=Lax`;
}

export function removeToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  // Expire the cookie via both `max-age=0` and a past `expires` date so
  // every UA (incl. older Safari) honours the invalidation on the first
  // attempt. SameSite must match the original (Lax) set in setToken().
  document.cookie = `${TOKEN_KEY}=; path=/; max-age=0; SameSite=Lax`;
  document.cookie = `${TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax`;
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

/**
 * Log the user out: call the API to clear the server-side cookie,
 * then drop the local token. The API call is best-effort — even if
 * it fails (network down, 404, etc.) we still clear local state so
 * the user is not left in a wedged "looks logged in" UI.
 */
export async function logout(): Promise<void> {
  const token = getToken();
  try {
    const headers: HeadersInit = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    await fetch(`${getApiBase()}/api/auth/logout`, {
      method: "POST",
      headers,
      credentials: "include",
    });
  } catch {
    // Swallow — logout must succeed locally regardless of the server.
  } finally {
    removeToken();
  }
}

/**
 * Wrapper around `fetch` that injects the Authorization header.
 * If the response is 401 (and the URL is not an auth endpoint), the
 * token is cleared and the user is redirected to /login.
 */
export async function fetchWithAuth(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  // credentials: "include" sends the mdl_access_token cookie (set by the
  // backend on POST /api/auth/login) alongside the Authorization header.
  // Without this, cross-origin deployments (prod) lose the cookie path and
  // /api/auth/me intermittently 401s when localStorage isn't yet populated.
  const res = await fetch(url, {
    credentials: "include",
    ...options,
    headers,
  });

  if (res.status === 401 && shouldHandle401(url)) {
    handleSessionExpired();
  }
  return res;
}
