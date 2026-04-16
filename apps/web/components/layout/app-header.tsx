"use client";

import { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, Truck, Map, Activity, Menu, X, Home, LogOut, User } from "lucide-react";
import { useAppStore, type AppMode } from "@/lib/store";
import { cn } from "@/lib/utils";
import { getToken, removeToken, fetchWithAuth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const MODES = [
  { key: "tv" as AppMode, label: "Modele TV", icon: Brain, path: "/donnees", color: "text-violet-400" },
  { key: "pl" as AppMode, label: "Modele PL", icon: Truck, path: "/donnees", color: "text-cyan-400" },
  { key: "carte" as AppMode, label: "Carte Debits", icon: Map, path: "/carte", color: "text-blue-400" },
  { key: "compteurs" as AppMode, label: "Compteurs", icon: Activity, path: "/compteurs", color: "text-emerald-400" },
] as const;

export function AppHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { mode, setMode, reset } = useAppStore();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);

  const isLanding = pathname === "/";
  const isAuthPage = pathname === "/login" || pathname === "/register";

  // Fetch current user email
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setUserEmail(null);
      return;
    }
    fetchWithAuth(`${API_BASE}/api/auth/me`)
      .then(async (res) => {
        if (res.ok) {
          const data = await res.json();
          setUserEmail(data.email);
        } else {
          setUserEmail(null);
        }
      })
      .catch(() => setUserEmail(null));
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

  function handleLogout() {
    removeToken();
    reset();
    router.push("/login");
  }

  // Don't show header on auth pages
  if (isAuthPage) return null;

  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.08] bg-[rgba(8,8,18,0.92)] backdrop-blur-xl">
      <div className="max-w-[1600px] mx-auto px-4 h-14 flex items-center justify-between gap-4">
        {/* Logo */}
        <button
          onClick={goHome}
          className="flex items-center gap-2 text-white hover:text-white/90 transition-colors shrink-0"
        >
          <Home size={18} className="text-indigo-400" />
          <span className="font-semibold text-sm hidden sm:block text-slate-100">
            MDL Redressement
          </span>
        </button>

        {/* Desktop nav */}
        <nav className="hidden md:flex items-center gap-1">
          {MODES.map((m) => {
            const active = mode === m.key;
            const Icon = m.icon;
            return (
              <button
                key={m.key}
                onClick={() => handleModeClick(m.key, m.path)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                  active
                    ? "bg-indigo-500/25 text-white border border-indigo-400/40"
                    : "text-slate-300 hover:text-white hover:bg-white/[0.06]"
                )}
              >
                <Icon size={14} className={active ? "text-indigo-300" : m.color} />
                {m.label}
              </button>
            );
          })}
        </nav>

        {/* Right side: mode badge + user info */}
        <div className="hidden md:flex items-center gap-3">
          {/* Mode badge */}
          {!isLanding && mode && (
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/25 text-indigo-200 border border-indigo-400/30 uppercase">
              {mode}
            </span>
          )}

          {/* User email + logout */}
          {userEmail && (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08]">
                <User size={12} className="text-slate-400" />
                <span className="text-[11px] text-slate-300 max-w-[160px] truncate">
                  {userEmail}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-all"
                title="Se deconnecter"
              >
                <LogOut size={14} />
              </button>
            </div>
          )}
        </div>

        {/* Mobile burger */}
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="md:hidden text-slate-300 hover:text-white"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="md:hidden border-t border-white/[0.08] bg-[rgba(8,8,18,0.95)]"
          >
            <div className="p-3 space-y-1">
              {MODES.map((m) => {
                const active = mode === m.key;
                const Icon = m.icon;
                return (
                  <button
                    key={m.key}
                    onClick={() => handleModeClick(m.key, m.path)}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all",
                      active
                        ? "bg-indigo-500/25 text-white"
                        : "text-slate-300 hover:text-white hover:bg-white/[0.06]"
                    )}
                  >
                    <Icon size={16} className={active ? "text-indigo-300" : m.color} />
                    {m.label}
                  </button>
                );
              })}

              {/* Mobile user info + logout */}
              {userEmail && (
                <div className="pt-2 mt-2 border-t border-white/[0.08]">
                  <div className="flex items-center justify-between px-3 py-2">
                    <div className="flex items-center gap-2">
                      <User size={14} className="text-slate-400" />
                      <span className="text-xs text-slate-300 truncate max-w-[200px]">
                        {userEmail}
                      </span>
                    </div>
                    <button
                      onClick={handleLogout}
                      className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-red-400 hover:bg-red-500/10 transition"
                    >
                      <LogOut size={14} />
                      <span>Deconnexion</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
