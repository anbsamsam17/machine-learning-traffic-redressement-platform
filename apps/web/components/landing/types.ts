/**
 * Shared landing types.
 *
 * These mirror the contract expected from `@/lib/content/landing` (agent R).
 * Until that module lands, `app/page.tsx` builds a fallback object that
 * conforms to these types.
 */

import type { LucideIcon } from "lucide-react";
import type { AppMode } from "@/lib/store";

/** A concrete mode (excludes the `null` variant from the store). */
export type LandingMode = Exclude<AppMode, null>;

export interface LandingModeContent {
  key: LandingMode;
  shortTitle: string;
  title: string;
  tagline: string;
  description: string;
  /** Up to ~3 metrics rendered as monospaced chips. */
  keyMetrics: string[];
  /** Accent palette key — drives icon color and hover border. */
  accent: "indigo" | "amber" | "cyan" | "emerald";
  icon: LucideIcon;
  cta: string;
}

export interface QuickStat {
  label: string;
  value: string;
  hint?: string;
}

export type ActivityKind = "training" | "map" | "compteurs" | "report";
export type ActivityStatus = "success" | "pending" | "error";

export interface ActivityItem {
  id: string;
  kind: ActivityKind;
  title: string;
  status: ActivityStatus;
  time: string;
}

export interface SamContent {
  welcomeBubble: string;
  welcomeSubtitle: string;
}

export interface FooterContent {
  legal: string;
  helpLabel?: string;
  helpHref?: string;
}

export interface LandingContent {
  eyebrow: string;
  title: string;
  subtitle: string;
  tagline: string;
  cta?: string;
  modes: LandingModeContent[];
  quickStats: QuickStat[];
  recentActivity: ActivityItem[];
  sam: SamContent;
  footer: FooterContent;
}
