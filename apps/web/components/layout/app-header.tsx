"use client";

import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, Truck, Map, Activity, Menu, X, Home } from "lucide-react";
import { useAppStore, type AppMode } from "@/lib/store";
import { cn } from "@/lib/utils";

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

  const isLanding = pathname === "/";

  function handleModeClick(m: AppMode, path: string) {
    if (m === mode) {
      // Already on this mode — go to current step
      router.push(path);
    } else {
      // Switch mode — reset state
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

  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-[rgba(5,5,16,0.85)] backdrop-blur-xl">
      <div className="max-w-[1600px] mx-auto px-4 h-14 flex items-center justify-between gap-4">
        {/* Logo */}
        <button
          onClick={goHome}
          className="flex items-center gap-2 text-slate-200 hover:text-white transition-colors shrink-0"
        >
          <Home size={18} className="text-indigo-400" />
          <span className="font-semibold text-sm hidden sm:block">
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
                    ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]"
                )}
              >
                <Icon size={14} className={active ? "text-indigo-400" : m.color} />
                {m.label}
              </button>
            );
          })}
        </nav>

        {/* Mode badge */}
        {!isLanding && mode && (
          <div className="hidden md:flex items-center">
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/20 uppercase">
              {mode}
            </span>
          </div>
        )}

        {/* Mobile burger */}
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="md:hidden text-slate-400 hover:text-white"
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
            className="md:hidden border-t border-white/[0.06] bg-[rgba(5,5,16,0.95)]"
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
                        ? "bg-indigo-500/20 text-indigo-300"
                        : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]"
                    )}
                  >
                    <Icon size={16} className={active ? "text-indigo-400" : m.color} />
                    {m.label}
                  </button>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
