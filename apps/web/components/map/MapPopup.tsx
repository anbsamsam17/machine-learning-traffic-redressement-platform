/**
 * MapPopup — utilities to render segment metadata inside a Maplibre Popup.
 *
 * Maplibre popups take raw HTML; we render directly from a typed properties
 * object. This module exports both a JSX helper (useful for tests / Storybook
 * later) and a `renderPopupHTML` function used by MapView.
 */

import type { GeoJsonProperties } from "geojson";

/** Properties we expect on each LineString feature (from /api/carte/generate). */
export interface SegmentProps {
  agregId?: string | number | null;
  // Débit TV redressé journalier — nom canonique JOr (anciennement TVr).
  JOr?: number | null;
  JOrmin?: number | null;
  JOrmax?: number | null;
  // Débit PL redressé journalier (présent seulement si modèle PL fourni).
  DPL?: number | null;
  DPLmin?: number | null;
  DPLmax?: number | null;
  // Heure de pointe matin (v/h) — présent seulement si modèle HPM fourni.
  PM?: number | null;
  PMmin?: number | null;
  PMmax?: number | null;
  // Heure de pointe soir (v/h) — présent seulement si modèle HPS fourni.
  PS?: number | null;
  PSmin?: number | null;
  PSmax?: number | null;
  FC?: number | null;
  // --- Legacy fallbacks (anciens GeoJSON) ---
  TVr?: number | null;
  TVrmin?: number | null;
  TVrmax?: number | null;
  /** Geometric Equivalent Hours (computed client-side, if available). */
  GEH?: number | null;
  [k: string]: unknown;
}

const NF_FR = new Intl.NumberFormat("fr-FR");

function fmt(v: number | null | undefined, unit = ""): string {
  if (v == null || (typeof v === "number" && !isFinite(v))) return "—";
  const rounded = Math.round(v as number);
  return unit ? `${NF_FR.format(rounded)} ${unit}` : NF_FR.format(rounded);
}

function rangeStr(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo == null && hi == null) return "—";
  if (lo == null || !isFinite(lo)) return `≤ ${fmt(hi)}`;
  if (hi == null || !isFinite(hi)) return `≥ ${fmt(lo)}`;
  return `${NF_FR.format(Math.round(lo))} – ${NF_FR.format(Math.round(hi))}`;
}

/**
 * Render the popup body as an HTML string consumable by Maplibre.
 * Styles are inlined (popup lives in a shadow-like DOM injected by maplibre,
 * so it does not inherit page styles consistently).
 */
export function renderPopupHTML(raw: GeoJsonProperties): string {
  const p = (raw ?? {}) as SegmentProps;

  const mono = "ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace";
  const cell = (label: string, value: string) =>
    `<div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.06)">
       <span style="color:#94a3b8;font-size:11px">${label}</span>
       <span style="color:#f8fafc;font-size:12px;font-family:${mono};font-variant-numeric:tabular-nums">${value}</span>
     </div>`;

  // A metric row: central value + [min – max] range, shown only when the
  // central value is present (TV-only cartes have no DPL/PM/PS columns).
  const metric = (
    label: string,
    unit: string,
    val: number | null | undefined,
    lo: number | null | undefined,
    hi: number | null | undefined,
  ): string => {
    if (val == null || !isFinite(Number(val))) return "";
    const r = rangeStr(lo, hi);
    const rangeSpan =
      r !== "—"
        ? `<span style="color:#94a3b8;font-size:11px;font-weight:400;margin-left:8px">${r}</span>`
        : "";
    return `<div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.06)">
       <span style="color:#94a3b8;font-size:11px">${label} <span style="color:#64748b">(${unit})</span></span>
       <span style="color:#f8fafc;font-size:12px;font-family:${mono};font-variant-numeric:tabular-nums">${fmt(val)}${rangeSpan}</span>
     </div>`;
  };

  // Canonical names with legacy fallback (JOr <- TVr).
  const jor = p.JOr ?? p.TVr;
  const jorMin = p.JOrmin ?? p.TVrmin;
  const jorMax = p.JOrmax ?? p.TVrmax;

  return `
    <div style="font-family:Inter,system-ui,sans-serif;color:#f8fafc;min-width:240px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,.1)">
        <span style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em">Tronçon</span>
        <span style="font-size:11px;font-family:${mono};color:#a5b4fc">#${p.agregId ?? "—"}</span>
      </div>
      ${metric("JOr", "véh/j", jor, jorMin, jorMax)}
      ${metric("DPL", "PL/j", p.DPL, p.DPLmin, p.DPLmax)}
      ${metric("PM", "véh/h", p.PM, p.PMmin, p.PMmax)}
      ${metric("PS", "véh/h", p.PS, p.PSmin, p.PSmax)}
      ${p.FC != null ? cell("FC", String(p.FC)) : ""}
      ${p.GEH != null ? cell("GEH", (p.GEH as number).toFixed(2)) : ""}
    </div>
  `;
}

/**
 * CSS injected once per MapView mount that overrides maplibre's default
 * popup container colors to match the dark theme.
 */
export const POPUP_CSS = `
  .maplibregl-popup-content {
    background: rgba(15, 20, 40, 0.96) !important;
    color: #f8fafc !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 12px !important;
    padding: 12px 14px !important;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.45) !important;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
  }
  .maplibregl-popup-tip { display: none !important; }
  .maplibregl-popup-close-button {
    color: #94a3b8 !important;
    font-size: 18px !important;
    padding: 4px 8px !important;
  }
  .maplibregl-popup-close-button:hover {
    background: rgba(255,255,255,.06) !important;
    color: #f8fafc !important;
  }
  .maplibregl-ctrl-attrib {
    background: rgba(15,20,40,.7) !important;
    color: #94a3b8 !important;
  }
  .maplibregl-ctrl-attrib a { color: #a5b4fc !important; }
`;
