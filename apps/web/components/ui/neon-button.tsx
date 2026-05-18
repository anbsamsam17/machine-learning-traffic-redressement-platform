"use client";

/**
 * Compat shim — the original NeonButton has been replaced by the
 * sober Button atom. Existing call sites import `NeonButton` so we
 * keep that name but delegate to `Button` to avoid touching 30+ files.
 *
 * Variant mapping:
 *   primary   -> primary
 *   secondary -> secondary
 *   ghost     -> ghost
 */
import type { ReactNode, MouseEventHandler } from "react";
import { Button } from "./button";

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
    <Button
      variant={variant}
      size="md"
      icon={icon}
      className={className}
      disabled={disabled}
      onClick={onClick}
      type={type}
      title={title}
    >
      {children}
    </Button>
  );
}
