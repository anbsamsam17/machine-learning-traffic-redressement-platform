/**
 * popup-html.ts — Constructeurs HTML pour les popups MapLibre de /visualisation.
 *
 * MapLibre attend une string HTML via popup.setHTML(). On garde donc des
 * builders qui retournent du string : extraits verbatim de l'ancien
 * app/visualisation/page.tsx (renderSegmentPopup + renderSensorPopup) pour
 * preserver 100% du rendu (couleurs, layout, microcopy, data-attributes).
 *
 * IMPORTANT : la string retournee contient un bouton avec data-copy-id="...".
 * Le caller doit attacher le listener apres .addTo(map) (cf. popup.getElement()
 * + .querySelector("[data-copy-id]")), comme le faisait l'ancienne page.
 */

const NF_FR = new Intl.NumberFormat("fr-FR");
const MONO = `ui-monospace, 'JetBrains Mono', 'SF Mono', Menlo, monospace`;

function streetViewUrl(lon: number, lat: number): string {
  return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${lat},${lon}`;
}

function fmtCellHtml(label: string, value: string): string {
  return `<div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.06)"><span style="color:#a0b0d8;font-size:11px">${label}</span><span style="color:#e6edf3;font-size:12px;font-family:${MONO};font-variant-numeric:tabular-nums">${value}</span></div>`;
}

function fmtNum(v: unknown, unit?: string): string {
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return unit
    ? `${NF_FR.format(Math.round(n))} ${unit}`
    : NF_FR.format(Math.round(n));
}

function fmtRange(lo: unknown, hi: unknown): string {
  const a = Number(lo);
  const b = Number(hi);
  if (!isFinite(a) && !isFinite(b)) return "—";
  if (!isFinite(a)) return `≤ ${NF_FR.format(Math.round(b))}`;
  if (!isFinite(b)) return `≥ ${NF_FR.format(Math.round(a))}`;
  return `${NF_FR.format(Math.round(a))} – ${NF_FR.format(Math.round(b))}`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export interface SegmentPopupContext {
  props: Record<string, unknown>;
  center: [number, number] | null;
}

export function renderSegmentPopupHtml({
  props,
  center,
}: SegmentPopupContext): string {
  const agregId = String(props.agregId ?? "—");
  const fc = props.FC ?? props.functional_class ?? null;
  const svUrl = center ? streetViewUrl(center[0], center[1]) : null;

  const fluxBlock = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0">
      <div style="background:rgba(34,211,238,.06);border:1px solid rgba(34,211,238,.18);border-radius:8px;padding:8px">
        <div style="font-size:9px;color:#a0b0d8;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">JOr</div>
        <div style="font-size:14px;color:#22d3ee;font-family:${MONO};font-weight:600">${fmtNum(props.JOr ?? props.TVr, "v/j")}</div>
        <div style="font-size:10px;color:#a0b0d8;font-family:${MONO};margin-top:3px">IC [${fmtRange(props.JOrmin ?? props.TVrmin, props.JOrmax ?? props.TVrmax)}]</div>
      </div>
      <div style="background:rgba(168,85,247,.06);border:1px solid rgba(168,85,247,.18);border-radius:8px;padding:8px">
        <div style="font-size:9px;color:#a0b0d8;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">DPL</div>
        <div style="font-size:14px;color:#c084fc;font-family:${MONO};font-weight:600">${fmtNum(props.DPL, "PL/j")}</div>
        <div style="font-size:10px;color:#a0b0d8;font-family:${MONO};margin-top:3px">IC [${fmtRange(props.DPLmin, props.DPLmax)}]</div>
      </div>
    </div>
  `;

  // HPM / HPS — affiches uniquement si les modeles correspondants sont
  // charges dans la pipeline carte (les props sont alors presentes). Couleurs
  // alignees sur les icones Sunrise/Sunset des panneaux pipeline HPM/HPS.
  const pmBlock =
    props.PM != null
      ? `
    <div style="margin-top:6px;padding-top:6px;border-top:1px solid #2a2f36">
      <div style="font-size:9px;color:#ff80b5;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">PM (pointe matin)</div>
      <div style="font-size:14px;color:#ff80b5;font-family:${MONO};font-weight:600">${fmtNum(props.PM, "v/h")}</div>
      <div style="font-size:10px;color:#a0b0d8;font-family:${MONO};margin-top:3px">IC [${fmtRange(props.PMmin, props.PMmax)}]</div>
    </div>
  `
      : "";

  const psBlock =
    props.PS != null
      ? `
    <div style="margin-top:6px;padding-top:6px;border-top:1px solid #2a2f36">
      <div style="font-size:9px;color:#c084fc;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">PS (pointe soir)</div>
      <div style="font-size:14px;color:#c084fc;font-family:${MONO};font-weight:600">${fmtNum(props.PS, "v/h")}</div>
      <div style="font-size:10px;color:#a0b0d8;font-family:${MONO};margin-top:3px">IC [${fmtRange(props.PSmin, props.PSmax)}]</div>
    </div>
  `
      : "";

  const fcdTv = props.TMJOFCDTV ?? props.TMJAFCDTV ?? props.FCD_TV ?? null;
  const fcdPl = props.TMJOFCDPL ?? props.TMJAFCDPL ?? props.FCD_PL ?? null;
  const fcdBlock =
    fcdTv !== null || fcdPl !== null
      ? `
    <div style="margin-top:6px">
      <div style="font-size:9px;color:#a0b0d8;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">FCD brut</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:6px;padding:6px 8px">
          <div style="font-size:9px;color:#a0b0d8">FCD TV</div>
          <div style="font-size:12px;color:#e6edf3;font-family:${MONO}">${fmtNum(fcdTv)}</div>
        </div>
        <div style="background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:6px;padding:6px 8px">
          <div style="font-size:9px;color:#a0b0d8">FCD PL</div>
          <div style="font-size:12px;color:#e6edf3;font-family:${MONO}">${fmtNum(fcdPl)}</div>
        </div>
      </div>
    </div>
  `
      : "";

  const detailKeys: { key: string; label: string }[] = [
    { key: "year_mapped", label: "year_mapped" },
    { key: "functional_class", label: "functional_class" },
    { key: "avg_distance_before_m", label: "avg_distance_before_m" },
    { key: "avg_min_distance_m", label: "avg_min_distance_m" },
    { key: "truck_avg_distance_before_m", label: "truck_avg_distance_before_m" },
    { key: "RAMP", label: "RAMP" },
    { key: "ROUNDABOUT", label: "ROUNDABOUT" },
    { key: "length_m", label: "length_m" },
  ];

  const details = detailKeys
    .map(({ key, label }) => {
      const v = props[key];
      if (v == null || v === "") return "";
      let s: string;
      if (typeof v === "number") {
        s = isFinite(v) ? NF_FR.format(Math.round(v * 100) / 100) : "—";
      } else {
        s = String(v);
      }
      return fmtCellHtml(label, s);
    })
    .filter(Boolean)
    .join("");

  const detailsBlock = details
    ? `<details style="margin-top:6px"><summary style="cursor:pointer;font-size:10px;color:#a0b0d8;text-transform:uppercase;letter-spacing:.06em;padding:4px 0">Inputs modele</summary><div style="margin-top:4px">${details}</div></details>`
    : "";

  const fcBadge =
    fc != null
      ? `<span style="font-size:10px;color:#a0b0d8;background:rgba(255,255,255,.06);padding:2px 6px;border-radius:4px;margin-left:6px">FC ${escapeHtml(String(fc))}</span>`
      : "";

  const ctas: string[] = [];
  if (svUrl) {
    ctas.push(
      `<a href="${svUrl}" target="_blank" rel="noopener" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:4px;padding:6px 10px;border-radius:6px;background:rgba(34,211,238,.1);border:1px solid rgba(34,211,238,.3);color:#22d3ee;font-size:11px;text-decoration:none">Street View</a>`,
    );
  }
  ctas.push(
    `<button type="button" data-copy-id="${escapeHtml(agregId)}" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:4px;padding:6px 10px;border-radius:6px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);color:#e6edf3;font-size:11px;cursor:pointer">Copier ID</button>`,
  );
  const ctaBlock = `<div style="display:flex;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,.08)">${ctas.join("")}</div>`;

  return `
    <div style="font-family:Inter,system-ui,sans-serif;color:#e6edf3;min-width:280px;max-width:360px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,.1)">
        <div style="display:flex;align-items:baseline;gap:6px;min-width:0;flex:1">
          <span style="font-size:10px;color:#a0b0d8;text-transform:uppercase;letter-spacing:.06em">Segment</span>
          <span style="font-size:12px;font-family:${MONO};color:#22d3ee;font-weight:600;overflow:hidden;text-overflow:ellipsis">#${escapeHtml(agregId)}</span>
          ${fcBadge}
        </div>
      </div>
      ${fluxBlock}
      ${pmBlock}
      ${psBlock}
      ${fcdBlock}
      ${detailsBlock}
      ${ctaBlock}
    </div>
  `;
}

export interface SensorPopupContext {
  props: Record<string, unknown>;
  center: [number, number] | null;
}

export function renderSensorPopupHtml({
  props,
  center,
}: SensorPopupContext): string {
  const id = String(props["Identifiant du Poste / Section"] ?? props.id ?? "—");
  const commune = props["Nom de la Commune"];
  const rd = props["RD"];
  const prd = props["PRD"];
  const type = props["Type de capteur"];
  const annee = props["Annee"];
  const tmjaTv = props["TMJA Tous Vehicules (veh/jour)"];
  const tmjaPl = props["TMJA Poids Lourds (veh/jour)"];
  const svUrl = center ? streetViewUrl(center[0], center[1]) : null;

  const rows: string[] = [];
  if (commune != null) rows.push(fmtCellHtml("Commune", String(commune)));
  if (rd != null) rows.push(fmtCellHtml("RD", String(rd)));
  if (prd != null) rows.push(fmtCellHtml("PRD", String(prd)));
  if (type != null) rows.push(fmtCellHtml("Type", String(type)));
  if (annee != null) rows.push(fmtCellHtml("Annee", String(annee)));
  rows.push(fmtCellHtml("TMJA TV", fmtNum(tmjaTv, "v/j")));
  rows.push(fmtCellHtml("TMJA PL", fmtNum(tmjaPl, "v/j")));

  const ctaBlock = svUrl
    ? `<div style="display:flex;gap:6px;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,.08)">
         <a href="${svUrl}" target="_blank" rel="noopener" style="flex:1;display:inline-flex;align-items:center;justify-content:center;gap:4px;padding:6px 10px;border-radius:6px;background:rgba(34,211,238,.1);border:1px solid rgba(34,211,238,.3);color:#22d3ee;font-size:11px;text-decoration:none">Street View</a>
       </div>`
    : "";

  return `
    <div style="font-family:Inter,system-ui,sans-serif;color:#e6edf3;min-width:260px;max-width:340px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,.1)">
        <div style="display:flex;align-items:baseline;gap:6px;min-width:0;flex:1">
          <span style="font-size:10px;color:#a0b0d8;text-transform:uppercase;letter-spacing:.06em">Capteur</span>
          <span style="font-size:12px;font-family:${MONO};color:#22d3ee;font-weight:600;overflow:hidden;text-overflow:ellipsis">${escapeHtml(id)}</span>
        </div>
      </div>
      ${rows.join("")}
      ${ctaBlock}
    </div>
  `;
}

/**
 * CSS injecte une seule fois dans <head> au mount de la page visualisation.
 * Style des popups MapLibre + attribution.
 */
export const POPUP_CSS = `
  .maplibregl-popup-content {
    background: rgba(15, 20, 36, 0.96) !important;
    color: #e6edf3 !important;
    border: 1px solid rgba(34, 211, 238, 0.18) !important;
    border-radius: 10px !important;
    padding: 12px 14px !important;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.55) !important;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
  }
  .maplibregl-popup-tip { display: none !important; }
  .maplibregl-popup-close-button {
    color: #a0b0d8 !important;
    font-size: 18px !important;
    padding: 2px 8px !important;
    line-height: 1 !important;
  }
  .maplibregl-popup-close-button:hover {
    background: rgba(255,255,255,.06) !important;
    color: #e6edf3 !important;
  }
  .maplibregl-ctrl-attrib {
    background: rgba(15,20,36,.7) !important;
    color: #a0b0d8 !important;
    font-size: 10px !important;
  }
  .maplibregl-ctrl-attrib a { color: #22d3ee !important; }
`;
