"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface GlowCardProps {
  children: ReactNode;
  className?: string;
  glowColor?: "accent" | "cyan" | "violet";
  onClick?: () => void;
}

const glowMap = {
  accent: "hover:shadow-[0_0_30px_rgba(99,102,241,0.3)]",
  cyan: "hover:shadow-[0_0_30px_rgba(6,182,212,0.3)]",
  violet: "hover:shadow-[0_0_30px_rgba(139,92,246,0.3)]",
};

export function GlowCard({
  children,
  className,
  glowColor = "accent",
  onClick,
}: GlowCardProps) {
  return (
    <motion.div
      whileHover={{ scale: 1.02, y: -2 }}
      whileTap={onClick ? { scale: 0.98 } : undefined}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
      onClick={onClick}
      className={cn(
        "glass p-6 transition-shadow duration-300 cursor-default",
        glowMap[glowColor],
        onClick && "cursor-pointer",
        className
      )}
    >
      {children}
    </motion.div>
  );
}
