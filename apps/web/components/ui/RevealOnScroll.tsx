"use client";

/** Wrapper qui anime ses enfants au scroll via GSAP ScrollTrigger. */
import { useRef, type ReactNode } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";
import { cn } from "@/lib/utils";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger);
}

export type RevealVariant = "fade" | "slide-up" | "slide-left" | "slide-right" | "scale";

export interface RevealOnScrollProps {
  children: ReactNode;
  /** Animation appliquee a chaque enfant direct (ou aux elements `[data-reveal]` si presents). */
  variant?: RevealVariant;
  /** Decalage initial avant le premier enfant (s). Defaut 0. */
  delay?: number;
  /** Decalage entre enfants (s). Defaut 0.08. */
  stagger?: number;
  /** Distance translation en px pour les variantes slide. Defaut 24. */
  distance?: number;
  /** Position dans la fenetre ou se declenche l'animation. Defaut "top 80%". */
  start?: string;
  /** Rejouer chaque fois que la section entre dans le viewport. Defaut false. */
  replay?: boolean;
  className?: string;
}

export function RevealOnScroll({
  children,
  variant = "slide-up",
  delay = 0,
  stagger = 0.08,
  distance = 24,
  start = "top 80%",
  replay = false,
  className,
}: RevealOnScrollProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  useGSAP(
    () => {
      const root = rootRef.current;
      if (!root) return;

      const explicit = root.querySelectorAll<HTMLElement>("[data-reveal]");
      const targets: HTMLElement[] =
        explicit.length > 0
          ? Array.from(explicit)
          : (Array.from(root.children) as HTMLElement[]);
      if (targets.length === 0) return;

      const fromVars: gsap.TweenVars = (() => {
        switch (variant) {
          case "fade":
            return { opacity: 0 };
          case "slide-up":
            return { opacity: 0, y: distance };
          case "slide-left":
            return { opacity: 0, x: distance };
          case "slide-right":
            return { opacity: 0, x: -distance };
          case "scale":
            return { opacity: 0, scale: 0.92 };
        }
      })();

      const mm = gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.set(targets, fromVars);
        gsap.to(targets, {
          opacity: 1,
          x: 0,
          y: 0,
          scale: 1,
          duration: 0.6,
          ease: "power2.out",
          stagger,
          delay,
          scrollTrigger: {
            trigger: root,
            start,
            toggleActions: replay ? "play reverse play reverse" : "play none none none",
          },
        });
      });
      // Reduced motion: laisser les elements a leur etat naturel (pas de set initial).
    },
    { scope: rootRef, dependencies: [variant, delay, stagger, distance, start, replay] }
  );

  return (
    <div ref={rootRef} className={cn(className)}>
      {children}
    </div>
  );
}
