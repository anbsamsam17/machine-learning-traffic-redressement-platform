/**
 * Auth helpers — token management.
 *
 * `fetchWithAuth` is kept as a thin compat shim around the new typed
 * apiClient (lib/api.ts). Prefer apiClient.* for new code.
 */

import { getApiBase } from "./api-url";

const TOKEN_KEY = "mdl_access_token";

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

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401 && !url.includes("/api/auth/")) {
    removeToken();
    if (typeof window !== "undefined") window.location.href = "/login";
  }
  return res;
}
