"use client";

/** Bouton premium avec effet magnetique GSAP : le contenu suit le curseur dans un rayon de 60px. */
import {
  forwardRef,
  useCallback,
  useRef,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
  cloneElement,
  isValidElement,
} from "react";
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { cn } from "@/lib/utils";

export type MagneticButtonVariant = "primary" | "secondary" | "ghost";
export type MagneticButtonSize = "sm" | "md" | "lg";

export interface MagneticButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  variant?: MagneticButtonVariant;
  size?: MagneticButtonSize;
  /** Si true, l'enfant unique recoit le ref + handlers (idiome shadcn Slot). */
  asChild?: boolean;
  /** Force d'attraction (0..1). Defaut 0.35. */
  strength?: number;
  /** Rayon d'activation en px. Defaut 60. */
  radius?: number;
  children: ReactNode;
}

const VARIANT: Record<MagneticButtonVariant, string> = {
  primary:
    "bg-accent text-accent-fg border border-accent shadow-[0_0_0_1px_rgba(99,102,241,0.35),0_8px_24px_-12px_rgba(99,102,241,0.6)]",
  secondary:
    "bg-bg-elevated text-text border border-border hover:border-border-strong",
  ghost:
    "bg-transparent text-text-muted hover:text-text border border-transparent hover:bg-bg-subtle",
};

const SIZE: Record<MagneticButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-base gap-2",
};

export const MagneticButton = forwardRef<HTMLButtonElement, MagneticButtonProps>(
  function MagneticButton(
    {
      variant = "primary",
      size = "md",
      asChild = false,
      strength = 0.35,
      radius = 60,
      className,
      children,
      ...rest
    },
    forwardedRef
  ) {
    const rootRef = useRef<HTMLElement | null>(null);
    const contentRef = useRef<HTMLSpanElement | null>(null);

    useGSAP(
      () => {
        const root = rootRef.current;
        const content = contentRef.current;
        if (!root || !content) return;

        const mm = gsap.matchMedia();
        mm.add("(prefers-reduced-motion: no-preference) and (hover: hover)", () => {
          const onMove = (event: PointerEvent) => {
            const rect = root.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            const dx = event.clientX - cx;
            const dy = event.clientY - cy;
            const dist = Math.hypot(dx, dy);
            if (dist > radius) {
              gsap.to(content, { x: 0, y: 0, duration: 0.4, ease: "power3.out" });
              return;
            }
            const pull = 1 - dist / radius;
            gsap.to(content, {
              x: dx * strength * pull,
              y: dy * strength * pull,
              duration: 0.25,
              ease: "power2.out",
            });
          };
          const onLeave = () => {
            gsap.to(content, {
              x: 0,
              y: 0,
              duration: 0.5,
              ease: "elastic.out(1, 0.45)",
            });
          };
          // Snap-back instantane au pointerdown : si l'utilisateur clique en
          // plein milieu de l'animation magnetique, le contenu revient au
          // centre AVANT que le browser dispatche le `click`. Garantit que le
          // visuel reste aligne avec le hit-test (sinon le click peut viser
          // un voisin DOM, observe sur la nav du header).
          const onDown = () => {
            gsap.set(content, { x: 0, y: 0 });
          };
          root.addEventListener("pointermove", onMove);
          root.addEventListener("pointerleave", onLeave);
          root.addEventListener("pointerdown", onDown);
          return () => {
            root.removeEventListener("pointermove", onMove);
            root.removeEventListener("pointerleave", onLeave);
            root.removeEventListener("pointerdown", onDown);
          };
        });
      },
      { dependencies: [strength, radius] }
    );

    const baseClasses = cn(
      "relative inline-flex items-center justify-center rounded-md font-medium",
      "transition-colors will-change-transform select-none",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
      "disabled:opacity-50 disabled:cursor-not-allowed",
      VARIANT[variant],
      SIZE[size],
      className
    );

    const mergedRef = useCallback(
      (node: HTMLElement | null) => {
        rootRef.current = node;
        if (typeof forwardedRef === "function") {
          forwardedRef(node as HTMLButtonElement | null);
        } else if (forwardedRef) {
          forwardedRef.current = node as HTMLButtonElement | null;
        }
      },
      [forwardedRef]
    );

    const inner = (
      <span ref={contentRef} className="inline-flex items-center gap-2 will-change-transform">
        {children}
      </span>
    );

    if (asChild && isValidElement(children)) {
      const child = children as ReactElement<{ className?: string; ref?: unknown }>;
      // Slot-like ref forwarding (shadcn idiom). The ref is a stable
      // useCallback, not read during render — safe to forward.
      // eslint-disable-next-line react-hooks/refs
      return cloneElement(child, {
        className: cn(baseClasses, child.props.className),
        ref: mergedRef,
      });
    }

    return (
      <button
        ref={mergedRef}
        type={rest.type ?? "button"}
        className={baseClasses}
        {...rest}
      >
        {inner}
      </button>
    );
  }
);
