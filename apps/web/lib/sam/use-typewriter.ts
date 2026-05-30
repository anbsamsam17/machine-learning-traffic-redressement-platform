"use client";

import * as React from "react";

/**
 * useTypewriter — affiche `text` progressivement, caractere par caractere.
 *
 * Comportement :
 *  - Si `text.length < skipThreshold` (defaut 30) : affiche tout d'un coup.
 *  - Si l'utilisateur a `prefers-reduced-motion` : affiche tout d'un coup.
 *  - Si `enabled` est false : retourne `text` direct.
 *  - Sinon : timer setInterval qui incremente l'index de 1 toutes les
 *    `msPerChar` ms (defaut 25 ms).
 *
 * Reset propre quand `text` change (nouvelle phrase = nouvelle frappe).
 */

interface UseTypewriterOptions {
  enabled?: boolean;
  msPerChar?: number;
  skipThreshold?: number;
}

const PREFERENCE = "(prefers-reduced-motion: no-preference)";

export function useTypewriter(
  text: string,
  options: UseTypewriterOptions = {}
): string {
  const { enabled = true, msPerChar = 25, skipThreshold = 30 } = options;
  const [displayed, setDisplayed] = React.useState<string>(text);

  React.useEffect(() => {
    // Court-circuit : on bypass dans 3 cas.
    if (!enabled || !text || text.length < skipThreshold) {
      setDisplayed(text ?? "");
      return;
    }
    const allowsMotion =
      typeof window !== "undefined" &&
      window.matchMedia(PREFERENCE).matches;
    if (!allowsMotion) {
      setDisplayed(text);
      return;
    }

    // Frappe progressive.
    setDisplayed("");
    let i = 0;
    const interval = window.setInterval(() => {
      i += 1;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) {
        window.clearInterval(interval);
      }
    }, msPerChar);
    return () => window.clearInterval(interval);
  }, [text, enabled, msPerChar, skipThreshold]);

  return displayed;
}
