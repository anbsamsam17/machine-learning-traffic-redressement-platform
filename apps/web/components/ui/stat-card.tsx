"use client";

import { motion } from "framer-motion";
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
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("glass-light p-4 flex items-center gap-4", className)}
    >
      {icon && (
        <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center text-accent">
          {icon}
        </div>
      )}
      <div className="min-w-0">
        <p className="text-xs text-muted truncate">{label}</p>
        <p
          className={cn(
            "text-xl font-bold mt-0.5",
            trend === "up" && "text-emerald-400",
            trend === "down" && "text-red-400",
            !trend && "text-foreground"
          )}
        >
          {value}
        </p>
      </div>
    </motion.div>
  );
}
