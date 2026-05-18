"use client";

/**
 * Mini 3-dot traffic light. Cycles red → amber → green on a 3s loop.
 * Each "on" state lifts opacity to 1, scales to 1.15× and adds a subtle
 * `box-shadow` glow for ~800ms. Base state is opacity 0.3.
 *
 * Sized ~50px wide × 10px tall. Designed to sit near the logo / header.
 *
 * Reduced motion: emerald stays on (opacity 1), others dim (0.3). Intuitive:
 * a green light = "ready to go".
 */

import { useRef } from "react";
import { useGSAP } from "@gsap/react";
import { signalCycle } from "@/lib/animations/traffic";

interface SignalLightsProps {
  className?: string;
}

export function SignalLights({ className }: SignalLightsProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const redRef = useRef<HTMLSpanElement>(null);
  const amberRef = useRef<HTMLSpanElement>(null);
  const greenRef = useRef<HTMLSpanElement>(null);

  useGSAP(
    () => {
      signalCycle(
        {
          red: redRef.current,
          amber: amberRef.current,
          green: greenRef.current,
        },
        { cycle: 3, onDuration: 0.8, dim: 0.3, glow: 8 }
      );
    },
    { scope: containerRef }
  );

  // Each dot: 10px circle, 6px gap, color set via inline style.
  // currentColor is set per-dot so the glow shadow uses the dot's color.
  const dotBase =
    "inline-block rounded-full w-[10px] h-[10px] [will-change:transform,opacity]";

  return (
    <div
      ref={containerRef}
      className={`inline-flex items-center gap-[6px] ${className ?? ""}`}
      aria-hidden="true"
      role="presentation"
    >
      <span
        ref={redRef}
        className={dotBase}
        style={{ backgroundColor: "#ef4444", color: "#ef4444", opacity: 0.3 }}
      />
      <span
        ref={amberRef}
        className={dotBase}
        style={{ backgroundColor: "#f59e0b", color: "#f59e0b", opacity: 0.3 }}
      />
      <span
        ref={greenRef}
        className={dotBase}
        style={{ backgroundColor: "#10b981", color: "#10b981", opacity: 0.3 }}
      />
    </div>
  );
}

export default SignalLights;
