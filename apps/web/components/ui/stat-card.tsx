"use client";

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon?: ReactNode;
  trend?: "up" | "down" | "neutral";
  className?: string;
}

export function StatCard({ label, value, icon, trend, className }: StatCardProps) {
  return (
    <div
      className={cn(
        "stat-card surface-elevated p-4 flex items-start gap-3 transition-colors",
        className
      )}
    >
      {icon && (
        <div className="shrink-0 w-8 h-8 rounded bg-accent-subtle flex items-center justify-center text-accent [&_svg]:size-4">
          {icon}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="text-[11px] uppercase tracking-wide text-text-muted truncate">
          {label}
        </p>
        <p
          className={cn(
            "font-mono text-xl font-semibold mt-1 tabular-nums leading-none",
            trend === "up" && "text-success",
            trend === "down" && "text-danger",
            !trend && "text-text"
          )}
          aria-live="polite"
        >
          {value}
        </p>
      </div>
    </div>
  );
}
