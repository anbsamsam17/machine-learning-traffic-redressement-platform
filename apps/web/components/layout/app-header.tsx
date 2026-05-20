"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  Brain,
  Truck,
  Map,
  Activity,
  Menu,
  X,
  Home,
  LogOut,
  User,
  Moon,
  Sun,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useAppStore, type AppMode } from "@/lib/store";
import { cn } from "@/lib/utils";
import { getToken, logout } from "@/lib/auth";
import { apiClient } from "@/lib/api";
import type { AuthMeResponse } from "@/lib/types/api";

const MODES = [
  { key: "tv" as AppMode, label: "ML Redressement FCD TV", icon: Brain, path: "/donnees" },
  { key: "pl" as AppMode, label: "Modele PL", icon: Truck, path: "/donnees" },
  { key: "carte" as AppMode, label: "Carte", icon: Map, path: "/carte" },
  { key: "compteurs" as AppMode, label: "Compteurs", icon: Activity, path: "/compteurs" },
] as const;

export function AppHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { mode, setMode, reset } = useAppStore();
  const { theme, setTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const firstLinkRef = useRef<HTMLButtonElement>(null);

  const isAuthPage = pathname === "/login" || pathname === "/register";

  useEffect(() => setMounted(true), []);

  // A11y — close mobile drawer on Escape and move focus to the first
  // interactive element when the drawer opens. Basic focus-trap.
  useEffect(() => {
    if (!mobileOpen) return;

    // Defer to give the enter animation a tick to mount.
    const focusTimer = window.setTimeout(() => {
      firstLinkRef.current?.focus();
    }, 50);

    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        setMobileOpen(false);
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      window.clearTimeout(focusTimer);
    };
  }, [mobileOpen]);

  // Fetch current user email — single call per pathname change.
  // The full TanStack migration of this hook is a follow-up; for now we
  // gate the call behind a token check so anonymous visitors don't hit
  // /api/auth/me on every navigation.
  useEffect(() => {
    if (!getToken()) {
      setUserEmail(null);
      return;
    }
    let cancelled = false;
    apiClient
      .get<AuthMeResponse>("/api/auth/me")
      .then((data) => {
        if (!cancelled) setUserEmail(data.email ?? null);
      })
      .catch(() => {
        if (!cancelled) setUserEmail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  function handleModeClick(m: AppMode, path: string) {
    if (m === mode) {
      router.push(path);
    } else {
      reset();
      setMode(m);
      router.push(path);
    }
    setMobileOpen(false);
  }

  function goHome() {
    reset();
    router.push("/");
    setMobileOpen(false);
  }

  async function handleLogout() {
    // Best-effort server-side cookie invalidation, then clear local
    // token + app state. `logout` always resolves, even on network error.
    await logout();
    reset();
    setUserEmail(null);
    // Hard navigation — bypass Next.js client cache so the middleware
    // re-reads cookies on the *next* request (router.push alone left
    // the user with a stale-looking header on the first click). The
    // explicit replace + reload combo also flushes any cached
    // /api/auth/me response held by SWR/TanStack queries elsewhere.
    if (typeof window !== "undefined") {
      window.location.replace("/login");
      return;
    }
    router.replace("/login");
  }

  function toggleTheme() {
    setTheme(theme === "dark" ? "light" : "dark");
  }

  if (isAuthPage) return null;

  return (
    <header
      role="banner"
      className="sticky top-0 z-50 border-b border-border bg-bg/95 backdrop-blur supports-[backdrop-filter]:bg-bg/80"
    >
      <div className="max-w-[1600px] mx-auto px-4 h-12 flex items-center justify-between gap-3">
        {/* Logo + breadcrumb */}
        <button
          onClick={goHome}
          className="flex items-center gap-2 text-text hover:text-accent transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded px-1"
          aria-label="Retour a l'accueil"
        >
          <Home size={16} className="text-accent" aria-hidden="true" />
          <span className="font-semibold text-sm hidden sm:block">
            MDL Redressement
          </span>
        </button>

        {/* Desktop nav */}
        <nav aria-label="Navigation principale" className="hidden md:flex items-center gap-0.5">
          {MODES.map((m) => {
            const active = mode === m.key;
            const Icon = m.icon;
            return (
              <button
                key={m.key}
                onClick={() => handleModeClick(m.key, m.path)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 h-7 rounded text-xs font-medium transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  active
                    ? "bg-accent-subtle text-accent"
                    : "text-text-muted hover:text-text hover:bg-bg-subtle"
                )}
              >
                <Icon size={14} aria-hidden="true" />
                {m.label}
              </button>
            );
          })}
        </nav>

        {/* Right side */}
        <div className="hidden md:flex items-center gap-2">
          {mounted && (
            <button
              onClick={toggleTheme}
              className="p-1.5 rounded text-text-muted hover:text-text hover:bg-bg-subtle transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-label={theme === "dark" ? "Activer le mode clair" : "Activer le mode sombre"}
            >
              {theme === "dark" ? (
                <Sun size={14} aria-hidden="true" />
              ) : (
                <Moon size={14} aria-hidden="true" />
              )}
            </button>
          )}

          {userEmail && (
            <div className="flex items-center gap-1">
              <div className="flex items-center gap-1.5 px-2 h-7 rounded bg-bg-elevated border border-border">
                <User size={12} className="text-text-muted" aria-hidden="true" />
                <span className="text-xs text-text-muted max-w-[180px] truncate">
                  {userEmail}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                title="Se deconnecter"
                aria-label="Se deconnecter"
              >
                <LogOut size={14} aria-hidden="true" />
              </button>
            </div>
          )}
        </div>

        {/* Mobile burger */}
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="md:hidden p-1.5 rounded text-text-muted hover:text-text hover:bg-bg-subtle transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-expanded={mobileOpen}
          aria-controls="mobile-nav-drawer"
          aria-label={mobileOpen ? "Fermer le menu" : "Ouvrir le menu"}
        >
          {mobileOpen ? <X size={18} aria-hidden="true" /> : <Menu size={18} aria-hidden="true" />}
        </button>
      </div>

      {/* Mobile menu — dialog drawer */}
      {mobileOpen && (
        <div
          id="mobile-nav-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          className="md:hidden border-t border-border bg-bg-elevated"
        >
          <div className="p-3 space-y-1">
            {MODES.map((m, idx) => {
              const active = mode === m.key;
              const Icon = m.icon;
              return (
                <button
                  key={m.key}
                  ref={idx === 0 ? firstLinkRef : undefined}
                  onClick={() => handleModeClick(m.key, m.path)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 h-9 rounded text-sm font-medium transition-colors",
                    active
                      ? "bg-accent-subtle text-accent"
                      : "text-text-muted hover:text-text hover:bg-bg-subtle"
                  )}
                >
                  <Icon size={14} aria-hidden="true" />
                  {m.label}
                </button>
              );
            })}
            {mounted && (
              <button
                onClick={toggleTheme}
                className="w-full flex items-center gap-2 px-3 h-9 rounded text-sm font-medium text-text-muted hover:text-text hover:bg-bg-subtle transition-colors"
              >
                {theme === "dark" ? <Sun size={14} aria-hidden="true" /> : <Moon size={14} aria-hidden="true" />}
                {theme === "dark" ? "Mode clair" : "Mode sombre"}
              </button>
            )}
            {userEmail && (
              <div className="pt-2 mt-2 border-t border-border">
                <div className="flex items-center justify-between px-3 py-2">
                  <div className="flex items-center gap-2">
                    <User size={14} className="text-text-muted" aria-hidden="true" />
                    <span className="text-xs text-text-muted truncate max-w-[200px]">
                      {userEmail}
                    </span>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="flex items-center gap-1 px-2 h-7 rounded text-xs text-danger hover:bg-danger/10 transition-colors"
                  >
                    <LogOut size={14} aria-hidden="true" />
                    <span>Deconnexion</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
