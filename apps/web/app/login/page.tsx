"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Home } from "lucide-react";
import { setToken } from "@/lib/auth";
import { apiClient, ApiError } from "@/lib/api";
import type { AuthLoginResponse } from "@/lib/types/api";
import { Button } from "@/components/ui/button";
import { fr } from "@/lib/i18n/fr";

export default function LoginPage() {
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
      const data = await apiClient.post<AuthLoginResponse>("/api/auth/login", {
        email,
        password,
      });
      setToken(data.access_token);
      router.push("/");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.detail : err instanceof Error ? err.message : "Erreur de connexion"
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
            <Home size={18} aria-hidden="true" />
          </div>
          <h1 className="text-xl font-semibold text-text">{fr.common.appName}</h1>
          <p className="text-sm text-text-muted">{fr.auth.login.subtitle}</p>
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
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border border-border bg-bg-elevated px-3 h-9 text-sm text-text placeholder:text-text-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              placeholder="Mot de passe"
            />
          </div>
          <Button type="submit" disabled={loading} variant="primary" size="md" className="w-full">
            {loading ? fr.auth.login.loading : fr.auth.login.submit}
          </Button>
        </form>

        <p className="text-center text-xs text-text-subtle">
          {fr.auth.login.noAccount}{" "}
          <Link href="/register" className="text-accent hover:underline">
            {fr.auth.login.register}
          </Link>
        </p>
      </div>
    </div>
  );
}
