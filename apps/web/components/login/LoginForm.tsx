"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { setToken } from "@/lib/auth";
import { apiUrl } from "@/lib/api-url";
import { parseApiError } from "@/lib/api";

/**
 * Sober login form — extracted from the previous page.tsx logic.
 * No glow. Focus ring visible. WCAG AA contrast.
 */
export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        // IMPORTANT: never redirect to /register on 401. Stay on /login
        // and display "Email ou mot de passe incorrect" (or whatever
        // FastAPI returns) in the <Alert> below. Pydantic 422 detail
        // arrays are stringified safely by parseApiError.
        const fallback =
          res.status === 401
            ? "Email ou mot de passe incorrect"
            : `Erreur ${res.status}`;
        throw new Error(parseApiError(data, fallback));
      }
      const data = await res.json();
      setToken(data.access_token);
      router.push("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Erreur de connexion");
      // Explicitly do NOT navigate on failure — keep the user on /login
      // so they can read the error and retry.
    } finally {
      setLoading(false);
    }
  }

  return (
    // login-glass = darker scrim + stronger blur so the form sits clearly
    // on top of the animated background. We keep the rounded-lg + indigo
    // focus ring tokens defined in globals.css.
    <div
      data-enter="form"
      className="login-glass relative w-full rounded-lg p-6"
    >
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-white">Connexion</h2>
        <p className="mt-1 text-xs text-zinc-300">
          Accédez à votre espace de travail
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300"
        >
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div>
          <label
            htmlFor="email"
            className="mb-1.5 block text-xs font-medium text-zinc-200"
          >
            Adresse email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-white/[0.1] bg-white/[0.03] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-colors focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/20"
            placeholder="email@exemple.com"
          />
        </div>

        <div>
          <label
            htmlFor="password"
            className="mb-1.5 block text-xs font-medium text-zinc-200"
          >
            Mot de passe
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-white/[0.1] bg-white/[0.03] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-colors focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-400/20"
            placeholder="••••••••"
          />
        </div>

        <button
          type="submit"
          // Explicit tabIndex={0} — defensive against any ancestor (e.g.
          // PageEnter / GSAP timeline) leaving a stale tabindex on the
          // wrapper that could otherwise drop the button out of the
          // natural tab sequence after email → password.
          tabIndex={0}
          disabled={loading}
          aria-disabled={loading}
          className="w-full rounded-md border border-indigo-500/60 bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/40 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? "Connexion…" : "Se connecter"}
        </button>
      </form>

      <p className="mt-5 text-center text-xs text-zinc-300">
        Pas encore de compte ?{" "}
        <Link
          href="/register"
          className="font-medium text-indigo-300 underline-offset-4 transition-colors hover:text-indigo-200 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400/40 rounded-sm"
        >
          Créer un compte
        </Link>
      </p>
    </div>
  );
}
