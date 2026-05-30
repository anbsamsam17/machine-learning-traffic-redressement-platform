"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { apiClient, ApiError } from "@/lib/api";
import { fr } from "@/lib/i18n/fr";
import { cn } from "@/lib/utils";
import {
  GlowCardPremium,
  MagneticButton,
  ShimmerText,
} from "@/components/ui";

/**
 * Premium register form — mirrors LoginForm visual treatment.
 *
 * Visual treatment:
 * - GlowCardPremium provides the conic-gradient halo
 * - On focus, a cyan ring + box-shadow grow around the card (CSS only,
 *   no remount — keeps form state stable across focus transitions)
 * - MagneticButton handles the "Creer le compte" submit
 * - ShimmerText for the gold "Inscription" heading
 */
export function RegisterForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError(fr.auth.register.passwordsMismatch);
      return;
    }
    if (password.length < 8) {
      setError(fr.auth.register.passwordTooShort);
      return;
    }
    setLoading(true);
    try {
      await apiClient.post("/api/auth/register", { email, password });
      router.push("/login");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.detail
          : err instanceof Error
          ? err.message
          : "Erreur lors de l'inscription"
      );
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
            variant="gold"
            duration={4.5}
            className="text-xl font-semibold"
          >
            Inscription
          </ShimmerText>
          <p className="mt-1.5 text-xs text-text-muted">
            {fr.auth.register.subtitle}
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
              {fr.auth.login.email}
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
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
              {fr.auth.login.password}
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              className="w-full rounded-md border border-white/[0.1] bg-white/[0.03] px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all focus:border-cyan-400/60 focus:ring-2 focus:ring-cyan-400/20 focus:shadow-[0_0_0_4px_rgba(6,182,212,0.08)]"
              placeholder="Minimum 8 caracteres"
            />
          </div>

          <div>
            <label
              htmlFor="confirm"
              className="mb-1.5 block text-xs font-medium text-zinc-200"
            >
              Confirmer le mot de passe
            </label>
            <input
              id="confirm"
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              className="w-full rounded-md border border-white/[0.1] bg-white/[0.03] px-3 py-2.5 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all focus:border-cyan-400/60 focus:ring-2 focus:ring-cyan-400/20 focus:shadow-[0_0_0_4px_rgba(6,182,212,0.08)]"
              placeholder="Retapez le mot de passe"
            />
          </div>

          <MagneticButton
            type="submit"
            variant="primary"
            size="lg"
            disabled={loading}
            aria-disabled={loading}
            strength={0.25}
            className="w-full uppercase tracking-wider text-sm"
          >
            {loading ? fr.auth.register.loading : fr.auth.register.submit}
            {!loading && (
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
            )}
          </MagneticButton>
        </form>

        <p className="mt-6 text-center text-xs text-text-muted">
          {fr.auth.register.hasAccount}{" "}
          <Link
            href="/login"
            className="font-medium text-cyan-300 underline-offset-4 transition-colors hover:text-cyan-200 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/40 rounded-sm"
          >
            {fr.auth.register.login}
          </Link>
        </p>
      </GlowCardPremium>
    </div>
  );
}
