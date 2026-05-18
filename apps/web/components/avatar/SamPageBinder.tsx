"use client";

/**
 * SamPageBinder — auto-bind Sam's mood + bubble copy to the current route.
 *
 * Mounted once at the root layout, this client component has no render
 * output. On every pathname change it looks up the matching entry in
 * `PAGE_MESSAGES` and pushes it into the global `samMood` store.
 *
 * Behaviour:
 *  - Exact-match first, longest-prefix fallback (see `getPageMessage`).
 *  - No `autoResetMs`: the chosen mood is persistent — it reflects the
 *    page's idle context, not a one-shot event.
 *  - When the route has no registered entry, the store is reset to its
 *    defaults instead of being left stale.
 *  - Pages that imperatively call `samMood.set(...)` for a transient
 *    state (e.g. "thinking" during training) will override the binder
 *    naturally — and the binder only re-fires on pathname change, so
 *    it won't fight transient updates.
 */

import { useEffect } from "react";
import { usePathname } from "next/navigation";

import { samMood } from "@/lib/sam/store";
import { getPageMessage } from "@/lib/sam/page-messages";

export function SamPageBinder(): null {
  const pathname = usePathname();

  useEffect(() => {
    const entry = getPageMessage(pathname);
    if (entry) {
      // Persistent — no autoResetMs. The next route change (or a page
      // imperatively calling samMood.set) is what supersedes it.
      samMood.set(entry.mood, entry.message);
    } else {
      // Unknown route — clear so we don't leak the previous page's
      // mood onto an unmapped surface.
      samMood.reset();
    }
  }, [pathname]);

  return null;
}

export default SamPageBinder;
