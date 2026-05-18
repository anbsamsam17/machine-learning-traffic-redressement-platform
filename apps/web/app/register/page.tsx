"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { UserPlus } from "lucide-react";
import { apiClient, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { fr } from "@/lib/i18n/fr";

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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
    <div className="min-h-screen flex items-center justify-center bg-bg p-4">
      <div className="w-full max-w-sm space-y-6">
        <header className="space-y-1.5 text-center">
          <div className="mx-auto w-10 h-10 rounded-md bg-accent-subtle border border-accent/30 flex items-center justify-center text-accent">
            <UserPlus size={18} aria-hidden="true" />
          </div>
          <h1 className="text-xl font-semibold text-text">{fr.auth.register.title}</h1>
          <p className="text-sm text-text-muted">{fr.auth.register.subtitle}</p>
        </header>

        {error && (
          <div
            role="alert"
            className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="block text-xs font-medium text-text-muted">
              {fr.auth.login.email}
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded border border-border bg-bg-elevated px-3 h-9 text-sm text-text placeholder:text-text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              placeholder="email@exemple.com"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="password" className="block text-xs font-medium text-text-muted">
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
              className="w-full rounded border border-border bg-bg-elevated px-3 h-9 text-sm text-text placeholder:text-text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              placeholder="Minimum 8 caracteres"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="confirm" className="block text-xs font-medium text-text-muted">
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
              className="w-full rounded border border-border bg-bg-elevated px-3 h-9 text-sm text-text placeholder:text-text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              placeholder="Retapez le mot de passe"
            />
          </div>
          <Button type="submit" disabled={loading} variant="primary" size="md" className="w-full">
            {loading ? fr.auth.register.loading : fr.auth.register.submit}
          </Button>
        </form>

        <p className="text-center text-xs text-text-subtle">
          {fr.auth.register.hasAccount}{" "}
          <Link href="/login" className="text-accent hover:underline">
            {fr.auth.register.login}
          </Link>
        </p>
      </div>
    </div>
  );
}
