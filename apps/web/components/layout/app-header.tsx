"use client";

import { useState, useEffect, useRef, useLayoutEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { gsap } from "gsap";
import {
  Car,
  Truck,
  Sunrise,
  Sunset,
  Map,
  Activity,
  MapPinned,
  AlertCircle,
  GitCompareArrows,
  Menu,
  X,
  LogOut,
  User,
  Home,
} from "lucide-react";
import { useAppStore, type AppMode } from "@/lib/store";
import { cn } from "@/lib/utils";
import { getToken, logout } from "@/lib/auth";
import { apiClient } from "@/lib/api";
import type { AuthMeResponse } from "@/lib/types/api";
import { MagneticButton, NeonBorder } from "@/components/ui";

const MODES = [
  { key: "tv" as AppMode, label: "Modele TV", icon: Car, path: "/donnees" },
  { key: "pl" as AppMode, label: "Modele PL", icon: Truck, path: "/donnees" },
  { key: "hpm" as AppMode, label: "Modele HPM", icon: Sunrise, path: "/donnees" },
  { key: "hps" as AppMode, label: "Modele HPS", icon: Sunset, path: "/donnees" },
  { key: "carte" as AppMode, label: "Carte", icon: Map, path: "/carte" },
  { key: "compteurs" as AppMode, label: "Compteurs", icon: Activity, path: "/compteurs" },
  { key: "visualisation" as AppMode, label: "Visualisation", icon: MapPinned, path: "/visualisation" },
  { key: "discontinuites" as AppMode, label: "Discontinuites", icon: AlertCircle, path: "/discontinuites" },
  { key: "evolution" as AppMode, label: "Evolution", icon: GitCompareArrows, path: "/evolution" },
] as const;

export function AppHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { mode, setMode, reset } = useAppStore();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const firstLinkRef = useRef<HTMLButtonElement>(null);

  // Animated underline pieces
  const navRef = useRef<HTMLElement>(null);
  const underlineRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const isAuthPage = pathname === "/login" || pathname === "/register";

  // A11y — close mobile drawer on Escape and move focus to the first
  // interactive element when the drawer opens.
  useEffect(() => {
    if (!mobileOpen) return;
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

  // Fetch user email (single call per pathname change) — gate behind token.
  useEffect(() => {
    if (!getToken()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
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

  // Animated underline — slides between the active nav item smoothly.
  // useLayoutEffect runs before paint so the underline never flashes.
  useLayoutEffect(() => {
    if (isAuthPage) return;
    const underline = underlineRef.current;
    const nav = navRef.current;
    if (!underline || !nav) return;

    const activeKey = mode ?? undefined;
    const target = activeKey ? itemRefs.current[activeKey] : null;

    if (!target) {
      gsap.to(underline, {
        opacity: 0,
        duration: 0.18,
        ease: "power2.out",
      });
      return;
    }

    const navRect = nav.getBoundingClientRect();
    const itemRect = target.getBoundingClientRect();
    const left = itemRect.left - navRect.left;
    const width = itemRect.width;

    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduceMotion) {
      gsap.set(underline, { x: left, width, opacity: 1 });
    } else {
      gsap.to(underline, {
        x: left,
        width,
        opacity: 1,
        duration: 0.32,
        ease: "power3.out",
      });
    }
  }, [mode, pathname, isAuthPage]);

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
    await logout();
    reset();
    setUserEmail(null);
    if (typeof window !== "undefined") {
      window.location.replace("/login");
      return;
    }
    router.replace("/login");
  }

  if (isAuthPage) return null;

  return (
    <header
      role="banner"
      className={cn(
        "sticky top-0 z-50 border-b border-border/60",
        "bg-bg/80 backdrop-blur-xl supports-[backdrop-filter]:bg-bg/60",
        // subtle gradient overlay for premium depth
        "before:absolute before:inset-0 before:pointer-events-none",
        "before:bg-gradient-to-b before:from-accent/[0.02] before:to-transparent"
      )}
    >
      <div className="relative max-w-[1600px] mx-auto px-4 h-14 flex items-center justify-between gap-3">
        {/* Logo + breadcrumb (Accueil) — MagneticButton ghost */}
        <MagneticButton
          variant="ghost"
          size="sm"
          onClick={goHome}
          strength={0.3}
          aria-label="Retour a l'accueil"
          className="shrink-0 text-text hover:text-accent"
        >
          <Home size={16} className="text-accent" aria-hidden="true" />
          <span className="font-semibold text-sm hidden sm:block">Accueil</span>
        </MagneticButton>

        {/* Desktop nav with animated underline */}
        <nav
          ref={navRef}
          aria-label="Navigation principale"
          className="relative hidden md:flex items-center gap-0.5"
        >
          {MODES.map((m) => {
            const active = mode === m.key;
            const Icon = m.icon;
            return (
              <button
                key={m.key}
                ref={(el) => {
                  itemRefs.current[m.key as string] = el;
                }}
                onClick={() => handleModeClick(m.key, m.path)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex items-center gap-1.5 px-2.5 h-8 rounded text-xs font-medium transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                  active
                    ? "text-accent"
                    : "text-text-muted hover:text-text"
                )}
              >
                <Icon size={14} aria-hidden="true" />
                {m.label}
              </button>
            );
          })}
          {/* Sliding underline — absolute positioned, animated via GSAP.
              Initially invisible until useLayoutEffect places it. */}
          <div
            ref={underlineRef}
            aria-hidden="true"
            className="pointer-events-none absolute bottom-0 left-0 h-[2px] rounded-full bg-accent"
            style={{
              width: 0,
              opacity: 0,
              boxShadow:
                "0 0 8px rgba(99,102,241,0.55), 0 0 1px rgba(99,102,241,0.85)",
            }}
          />
        </nav>

        {/* Right side — user pill + logout */}
        <div className="hidden md:flex items-center gap-2">
          {userEmail && (
            <div className="flex items-center gap-1.5">
              <NeonBorder
                tone="accent"
                thickness={1}
                rotate={false}
                speed={4.5}
                className="rounded-full"
              >
                <div className="flex items-center gap-1.5 px-2.5 h-7 rounded-full">
                  <User
                    size={12}
                    className="text-text-muted"
                    aria-hidden="true"
                  />
                  <span className="text-xs text-text-muted max-w-[180px] truncate">
                    {userEmail}
                  </span>
                </div>
              </NeonBorder>
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
          {mobileOpen ? (
            <X size={18} aria-hidden="true" />
          ) : (
            <Menu size={18} aria-hidden="true" />
          )}
        </button>
      </div>

      {/* Mobile menu — dialog drawer */}
      {mobileOpen && (
        <div
          id="mobile-nav-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          className="md:hidden border-t border-border bg-bg-elevated/95 backdrop-blur-xl"
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
            {userEmail && (
              <div className="pt-2 mt-2 border-t border-border">
                <div className="flex items-center justify-between px-3 py-2">
                  <div className="flex items-center gap-2">
                    <User
                      size={14}
                      className="text-text-muted"
                      aria-hidden="true"
                    />
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
