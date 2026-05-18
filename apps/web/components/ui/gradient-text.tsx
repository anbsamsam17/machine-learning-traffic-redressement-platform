/**
 * Compat shim — gradient text is consumer/playful and out of place in
 * the sober redesign. We keep the component name (used by 7+ files)
 * but render plain semantic text.
 */
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface GradientTextProps {
  children: ReactNode;
  className?: string;
  as?: "h1" | "h2" | "h3" | "h4" | "span" | "p";
}

export function GradientText({
  children,
  className,
  as: Tag = "span",
}: GradientTextProps) {
  return <Tag className={cn("font-semibold text-text", className)}>{children}</Tag>;
}
