"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface ModeCardProps {
  title: string;
  description: string;
  icon: ReactNode;
  glowColor: "accent" | "cyan" | "violet";
  onClick: () => void;
  delay?: number;
}

const colorMap = {
  accent: {
    border: "border-indigo-400/20 hover:border-indigo-400/50",
    glow: "hover:shadow-[0_0_40px_rgba(99,102,241,0.25)]",
    iconBg: "bg-indigo-500/15 text-indigo-400",
  },
  cyan: {
    border: "border-cyan-400/20 hover:border-cyan-400/50",
    glow: "hover:shadow-[0_0_40px_rgba(6,182,212,0.25)]",
    iconBg: "bg-cyan-500/15 text-cyan-400",
  },
  violet: {
    border: "border-violet-400/20 hover:border-violet-400/50",
    glow: "hover:shadow-[0_0_40px_rgba(139,92,246,0.25)]",
    iconBg: "bg-violet-500/15 text-violet-400",
  },
};

export function ModeCard({
  title,
  description,
  icon,
  glowColor,
  onClick,
  delay = 0,
}: ModeCardProps) {
  const colors = colorMap[glowColor];
  return (
    <motion.button
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, type: "spring", stiffness: 200, damping: 20 }}
      whileHover={{ scale: 1.03, y: -4 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className={cn(
        "glass p-8 text-left transition-all duration-300 group",
        colors.border,
        colors.glow
      )}
    >
      <div
        className={cn(
          "w-14 h-14 rounded-xl flex items-center justify-center mb-5 transition-transform group-hover:scale-110",
          colors.iconBg
        )}
      >
        {icon}
      </div>
      <h3 className="text-lg font-bold text-white mb-2">{title}</h3>
      <p className="text-sm text-slate-300 leading-relaxed">{description}</p>
    </motion.button>
  );
}
