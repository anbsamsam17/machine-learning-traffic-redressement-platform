"use client";

import * as React from "react";
import Image from "next/image";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { cn } from "@/lib/utils";
import { samMoodImage, type SamMood } from "@/lib/sam/moods";

/**
 * SamLottie — Sam vivant.
 *
 * Pas un Lottie JSON externe : on simule une animation idle pro et controlable
 * via une timeline GSAP en boucle infinie (respirement + sway + micro skew),
 * couplee a une aura mood-aware (box-shadow color-shift).
 *
 * Pourquoi pas un JSON Bodymovin ?
 *  - Plus lourd, plus risque (parser + runtime).
 *  - Idle subtil = transform pur, GSAP fait ca a 60fps sans dependance.
 *  - Controllable : pause sur mood change, kill au unmount, prefers-reduced-motion.
 *
 * Composition :
 *  - Wrapper aura (box-shadow color-shift, pulse selon mood).
 *  - Wrapper breath (scale 1 -> 1.012 -> 1, 3.6s).
 *  - Wrapper sway (y 0 -> -2 -> 0, 4.2s + skewX +-0.4deg, 7s).
 *  - Image crossfade entre les moods (pilote par le parent ou interne).
 *
 * API minimale : { mood, size, className, imgClassName, priority }.
 */

const PREFERENCE = "(prefers-reduced-motion: no-preference)";

/**
 * Aura par mood — box-shadow color-shift autour de l'avatar.
 * Couleurs alignees sur la charte (amber/cyan/violet/green/red).
 */
const MOOD_AURA: Record<SamMood, { color: string; pulse: boolean }> = {
  welcome: { color: "rgba(255, 176, 0, 0.45)", pulse: false },
  based: { color: "rgba(34, 211, 238, 0.30)", pulse: false },
  analysing: { color: "rgba(34, 211, 238, 0.55)", pulse: true },
  thinking: { color: "rgba(167, 139, 250, 0.55)", pulse: true },
  goodjob: { color: "rgba(34, 197, 94, 0.55)", pulse: true },
  error: { color: "rgba(239, 68, 68, 0.60)", pulse: false },
};

export interface SamLottieProps {
  mood: SamMood;
  size?: number;
  className?: string;
  imgClassName?: string;
  priority?: boolean;
  /** Permet de couper l'aura (utile quand le parent en gere une autre). */
  withAura?: boolean;
}

export const SamLottie = React.forwardRef<HTMLDivElement, SamLottieProps>(
  function SamLottie(
    {
      mood,
      size = 128,
      className,
      imgClassName,
      priority = false,
      withAura = true,
    },
    forwardedRef
  ) {
    const rootRef = React.useRef<HTMLDivElement | null>(null);
    const auraRef = React.useRef<HTMLDivElement | null>(null);
    const breathRef = React.useRef<HTMLDivElement | null>(null);
    const swayRef = React.useRef<HTMLDivElement | null>(null);
    const imgWrapRef = React.useRef<HTMLDivElement | null>(null);
    const prevMoodRef = React.useRef<SamMood | null>(null);

    React.useImperativeHandle(
      forwardedRef,
      () => rootRef.current as HTMLDivElement
    );

    // Idle infinite loop — breath + sway + skew. Pause sur unmount.
    useGSAP(
      () => {
        const breath = breathRef.current;
        const sway = swayRef.current;
        if (!breath || !sway) return;

        const mm = gsap.matchMedia();
        mm.add(PREFERENCE, () => {
          // Respirement : scale tres subtil.
          const tBreath = gsap.to(breath, {
            scale: 1.012,
            duration: 3.6,
            ease: "sine.inOut",
            yoyo: true,
            repeat: -1,
          });

          // Sway vertical : Sam respire et bouge legerement.
          const tSway = gsap.to(sway, {
            y: -2,
            duration: 4.2,
            ease: "sine.inOut",
            yoyo: true,
            repeat: -1,
          });

          // Skew subtil : decale la phase pour eviter un effet mecanique.
          const tSkew = gsap.to(sway, {
            skewX: 0.4,
            duration: 7,
            ease: "sine.inOut",
            yoyo: true,
            repeat: -1,
            delay: 1.3,
          });

          return () => {
            tBreath.kill();
            tSway.kill();
            tSkew.kill();
            gsap.set([breath, sway], {
              clearProps: "transform,scale,y,skewX",
            });
          };
        });

        return () => mm.revert();
      },
      { scope: rootRef }
    );

    // Aura : pulse pour analysing/thinking/goodjob, statique pour welcome/based/error.
    useGSAP(
      () => {
        const aura = auraRef.current;
        if (!aura || !withAura) return;
        const config = MOOD_AURA[mood];

        const mm = gsap.matchMedia();
        mm.add(PREFERENCE, () => {
          gsap.killTweensOf(aura);
          if (config.pulse) {
            // Pulse : box-shadow scale dynamique.
            const tween = gsap.fromTo(
              aura,
              {
                boxShadow: `0 0 0px 0px ${config.color}`,
                opacity: 0.6,
              },
              {
                boxShadow: `0 0 32px 6px ${config.color}`,
                opacity: 1,
                duration: 1.4,
                ease: "sine.inOut",
                yoyo: true,
                repeat: -1,
              }
            );
            return () => {
              tween.kill();
              gsap.set(aura, { clearProps: "boxShadow,opacity" });
            };
          } else {
            // Statique : aura douce permanente.
            gsap.to(aura, {
              boxShadow: `0 0 24px 4px ${config.color}`,
              opacity: 1,
              duration: 0.6,
              ease: "power2.out",
            });
            return () => {
              gsap.set(aura, { clearProps: "boxShadow,opacity" });
            };
          }
        });

        // Cas reduced-motion : pose finale immediate.
        if (
          typeof window !== "undefined" &&
          !window.matchMedia(PREFERENCE).matches
        ) {
          aura.style.boxShadow = `0 0 24px 4px ${config.color}`;
          aura.style.opacity = "1";
        }

        return () => mm.revert();
      },
      { dependencies: [mood, withAura], scope: rootRef }
    );

    // Crossfade image sur mood change + shake pour error.
    useGSAP(
      () => {
        const el = imgWrapRef.current;
        if (!el) return;
        if (prevMoodRef.current === null) {
          prevMoodRef.current = mood;
          return;
        }
        if (prevMoodRef.current === mood) return;
        const previousMood = prevMoodRef.current;
        prevMoodRef.current = mood;

        const mm = gsap.matchMedia();
        mm.add(PREFERENCE, () => {
          gsap.killTweensOf(el);
          const tl = gsap.timeline();
          tl.fromTo(
            el,
            { opacity: 0.2, scale: 0.95 },
            { opacity: 1, scale: 1, duration: 0.35, ease: "power2.out" }
          );
          // Shake supplementaire pour error.
          if (mood === "error" && previousMood !== "error") {
            tl.fromTo(
              el,
              { x: 0 },
              {
                x: 6,
                duration: 0.05,
                yoyo: true,
                repeat: 5,
                ease: "power1.inOut",
                onComplete: () => gsap.set(el, { x: 0 }),
              },
              "<0.05"
            );
          }
          return () => {
            tl.kill();
          };
        });

        return () => mm.revert();
      },
      { dependencies: [mood], scope: rootRef }
    );

    return (
      <div
        ref={rootRef}
        className={cn("relative", className)}
        style={{ width: size, height: size }}
      >
        {withAura ? (
          <div
            ref={auraRef}
            aria-hidden="true"
            className="pointer-events-none absolute inset-2 rounded-full"
            style={{ opacity: 0, willChange: "box-shadow, opacity" }}
          />
        ) : null}
        <div
          ref={breathRef}
          className="relative size-full will-change-transform"
          style={{ transformOrigin: "50% 90%" }}
        >
          <div
            ref={swayRef}
            className="relative size-full will-change-transform"
            style={{ transformOrigin: "50% 90%" }}
          >
            <div ref={imgWrapRef} className="relative size-full">
              <Image
                src={samMoodImage(mood)}
                alt=""
                fill
                sizes={`${size}px`}
                priority={priority}
                className={cn("object-contain", imgClassName)}
              />
            </div>
          </div>
        </div>
      </div>
    );
  }
);

export default SamLottie;
