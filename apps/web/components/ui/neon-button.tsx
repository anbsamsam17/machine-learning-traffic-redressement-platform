"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { ReactNode, MouseEventHandler } from "react";

interface NeonButtonProps {
  variant?: "primary" | "secondary" | "ghost";
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
  disabled?: boolean;
  onClick?: MouseEventHandler<HTMLButtonElement>;
  type?: "button" | "submit" | "reset";
  title?: string;
}

const variants = {
  primary:
    "bg-accent text-white neon-glow hover:bg-accent/90 border border-accent/50",
  secondary:
    "bg-surface-light text-foreground border border-border hover:border-accent/40 hover:shadow-[0_0_15px_rgba(99,102,241,0.2)]",
  ghost:
    "bg-transparent text-muted hover:text-foreground hover:bg-surface-light border border-transparent",
};

export function NeonButton({
  variant = "primary",
  children,
  icon,
  className,
  disabled,
  onClick,
  type = "button",
  title,
}: NeonButtonProps) {
  return (
    <motion.button
      whileHover={disabled ? undefined : { scale: 1.03 }}
      whileTap={disabled ? undefined : { scale: 0.97 }}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3 text-sm font-medium transition-all duration-200",
        variants[variant],
        disabled && "opacity-40 cursor-not-allowed",
        className
      )}
      disabled={disabled}
      onClick={onClick}
      type={type}
      title={title}
    >
      {icon}
      {children}
    </motion.button>
  );
}
