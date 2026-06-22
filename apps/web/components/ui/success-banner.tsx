"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, X } from "lucide-react";

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
    // Intentional: reset the dismiss animation state when the banner becomes
    // visible so the auto-dismiss timer restarts cleanly.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDismissing(false);
    const timer = setTimeout(() => {
      setDismissing(true);
      setTimeout(onClose, 200);
    }, autoDismiss);
    return () => clearTimeout(timer);
  }, [visible, autoDismiss, onClose]);

  if (!visible) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-4 right-4 z-[100] max-w-sm"
      style={{
        transition: "opacity .2s, transform .2s",
        opacity: dismissing ? 0 : 1,
        transform: dismissing ? "translateX(8px)" : "translateX(0)",
      }}
    >
      <div className="surface-elevated border-success/40 flex items-center gap-3 p-3">
        <CheckCircle2 size={18} className="text-success shrink-0" aria-hidden="true" />
        <p className="text-sm text-text flex-1">{message}</p>
        <button
          onClick={() => {
            setDismissing(true);
            setTimeout(onClose, 200);
          }}
          className="p-1 rounded text-text-muted hover:text-text hover:bg-bg-subtle transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-label="Fermer"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
