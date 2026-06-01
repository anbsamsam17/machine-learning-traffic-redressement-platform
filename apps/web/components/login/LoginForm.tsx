"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { setToken } from "@/lib/auth";
import { apiUrl } from "@/lib/api-url";
import { parseApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  GlowCardPremium,
  MagneticButton,
  ShimmerText,
} from "@/components/ui";

/**
 * Premium login form — uses UX5 primitives.
 *
 * Visual treatment:
 * - GlowCardPremium provides the conic-gradient halo
 * - On focus, a cyan ring + box-shadow grow around the card (CSS only,
 *   no remount — avoids losing form state mid-submit)
 * - MagneticButton handles the "Se connecter" submit
 * - ShimmerText for the gold "Connexion" heading
 */
export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState(false);

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
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className={cn(
        "relative w-full transition-all duration-300",
        "rounded-lg",
        focused
          ? "shadow-[0_0_0_1px_rgba(6,182,212,0.55),0_0_24px_rgba(6,182,212,0.25)]"
          : "shadow-[0_0_0_1px_rgba(255,255,255,0.04)]"
      )}
    >
      <GlowCardPremium
        tone="accent"
        intensity={0.5}
        interactive={false}
        data-enter="form"
        className="relative w-full"
      >
        <div className="mb-6">
          <ShimmerText
            as="h2"
            variant="neon-white"
            duration={5.5}
            className="text-xl font-semibold"
          >
            Connexion
          </ShimmerText>
          <p className="mt-1.5 text-xs text-text-muted">
            Accedez a votre espace de travail
          </p>
        </div>

        {error && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
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
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              className="w-full rounded-md border border-white/[0.1] bg-white/[0.03] px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all focus:border-cyan-400/60 focus:ring-2 focus:ring-cyan-400/20 focus:shadow-[0_0_0_4px_rgba(6,182,212,0.08)]"
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
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              className="w-full rounded-md border border-white/[0.1] bg-white/[0.03] px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all focus:border-cyan-400/60 focus:ring-2 focus:ring-cyan-400/20 focus:shadow-[0_0_0_4px_rgba(6,182,212,0.08)]"
              placeholder="••••••••"
            />
          </div>

          <MagneticButton
            type="submit"
            variant="primary"
            size="lg"
            tabIndex={0}
            disabled={loading}
            aria-disabled={loading}
            strength={0.25}
            className="w-full uppercase tracking-wider text-sm"
          >
            {loading ? "Connexion..." : "Se connecter"}
            {!loading && (
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
            )}
          </MagneticButton>
        </form>

        <p className="mt-6 text-center text-xs text-text-muted">
          Pas encore de compte ?{" "}
          <Link
            href="/register"
            className="font-medium text-cyan-300 underline-offset-4 transition-colors hover:text-cyan-200 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/40 rounded-sm"
          >
            Creer un compte
          </Link>
        </p>
      </GlowCardPremium>
    </div>
  );
}
