"use client";

import { useRef } from "react";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { hoverLift, hoverReset } from "@/lib/animations/gsap";
import type { ReactNode } from "react";

interface ModeCardProps {
  title: string;
  description: string;
  icon: ReactNode;
  glowColor?: "accent" | "cyan" | "violet";
  onClick: () => void;
  delay?: number;
}

export function ModeCard({
  title,
  description,
  icon,
  onClick,
}: ModeCardProps) {
  const ref = useRef<HTMLButtonElement>(null);

  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      onMouseEnter={() => ref.current && hoverLift(ref.current)}
      onMouseLeave={() => ref.current && hoverReset(ref.current)}
      className={cn(
        "group surface-elevated p-5 text-left transition-colors",
        "hover:border-border-strong",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      )}
    >
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="w-9 h-9 rounded-md bg-accent-subtle flex items-center justify-center text-accent [&_svg]:size-5">
          {icon}
        </div>
        <ArrowRight
          size={16}
          className="text-text-subtle group-hover:text-accent transition-colors mt-1"
          aria-hidden="true"
        />
      </div>
      <h3 className="text-base font-semibold text-text mb-1.5">{title}</h3>
      <p className="text-sm text-text-muted leading-relaxed">{description}</p>
    </button>
  );
}
