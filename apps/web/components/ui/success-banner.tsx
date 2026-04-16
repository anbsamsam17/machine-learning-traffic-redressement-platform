"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface SuccessBannerProps {
  message: string;
  visible: boolean;
  onClose: () => void;
  autoDismiss?: number;
}

export function SuccessBanner({
  message,
  visible,
  onClose,
  autoDismiss = 5000,
}: SuccessBannerProps) {
  const [dismissing, setDismissing] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setDismissing(false);
    const timer = setTimeout(() => {
      setDismissing(true);
      setTimeout(onClose, 300);
    }, autoDismiss);
    return () => clearTimeout(timer);
  }, [visible, autoDismiss, onClose]);

  if (!visible) return null;

  return (
    <div
      className={cn(
        "fixed top-4 right-4 z-[100] max-w-sm",
        dismissing ? "animate-slide-out" : "animate-slide-in"
      )}
    >
      <div className="relative overflow-hidden rounded-xl border border-emerald-500/30 bg-emerald-950/60 backdrop-blur-xl shadow-[0_0_30px_rgba(16,185,129,0.15)]">
        <div className="flex items-center gap-3 px-4 py-3">
          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center">
            <CheckCircle2 size={18} className="text-emerald-400" />
          </div>
          <p className="text-sm font-medium text-emerald-100 flex-1">
            {message}
          </p>
          <button
            onClick={() => {
              setDismissing(true);
              setTimeout(onClose, 300);
            }}
            className="flex-shrink-0 p-1 rounded-md text-emerald-400/60 hover:text-emerald-300 hover:bg-emerald-500/10 transition-colors"
          >
            <X size={14} />
          </button>
        </div>
        {/* Animated progress bar at bottom */}
        <div className="h-0.5 bg-emerald-900/50">
          <div
            className="h-full bg-emerald-400/60 rounded-full"
            style={{
              animation: `shrink-bar ${autoDismiss}ms linear forwards`,
            }}
          />
        </div>
        <style jsx>{`
          @keyframes shrink-bar {
            0% { width: 100%; }
            100% { width: 0%; }
          }
        `}</style>
      </div>
    </div>
  );
}
