"use client";

/**
 * NodePanel — panneau lateral droit du detail d'un noeud discontinuites.
 *
 * Extrait verbatim de app/discontinuites/page.tsx. Le composant est un
 * "dumb component" : il recoit `feature` (node selectionne) + callbacks
 * (close, copyId) et n'a aucun effet de bord sur la map. La page parent
 * orchestre la selection + le feature-state MapLibre.
 *
 * Le sous-composant FluxCell est inclus en bas (utilise uniquement par
 * NodePanel, pas de raison d'en faire un fichier separe).
 */

import { X } from "lucide-react";

const NF_FR = new Intl.NumberFormat("fr-FR");

// ---------------------------------------------------------------------------
// Types echanges avec la page parent
// ---------------------------------------------------------------------------

export type CauseKey =
  | "FCD_TV_cliff"
  | "FCD_PL_cliff"
  | "Coverage_gap"
  | "Distance_anomaly"
  | "RAMP_asymmetry"
  | "ROUNDABOUT_asymmetry"
  | "FC_transition"
  | "Unexplained";

export type TopologyKey = "Bretelle" | "Carrefour" | "Continuite";

export interface SelectedNode {
  id: string | number;
  coords: [number, number];
  properties: Record<string, unknown>;
}

interface DriverScore {
  rank?: number;
  ratio?: number;
  delta?: number;
  min?: number | string;
  max?: number | string;
}

interface EdgeRecord {
  label?: string;
  TVr?: number;
  JOr?: number;
  inputs?: Record<string, number | null>;
}

// ---------------------------------------------------------------------------
// Palettes + libelles (alignes avec discontinuites/page.tsx)
// ---------------------------------------------------------------------------

const PALETTE: Record<CauseKey, string> = {
  FCD_TV_cliff: "#E41A1C",
  FCD_PL_cliff: "#B30000",
  Coverage_gap: "#7B1FA2",
  Distance_anomaly: "#FF7F00",
  RAMP_asymmetry: "#FFB000",
  ROUNDABOUT_asymmetry: "#A65628",
  FC_transition: "#377EB8",
  Unexplained: "#999999",
};

const TOPO_PALETTE: Record<TopologyKey, string> = {
  Bretelle: "#87CEEB",
  Carrefour: "#4682B4",
  Continuite: "#FFA07A",
};

const CAUSE_LABELS_FR: Record<CauseKey, string> = {
  FCD_TV_cliff: "Falaise FCD VL",
  FCD_PL_cliff: "Falaise FCD PL",
  Coverage_gap: "Trou de couverture FCD",
  Distance_anomaly: "Anomalie de distance",
  RAMP_asymmetry: "Bretelle asymetrique",
  ROUNDABOUT_asymmetry: "Rond-point asymetrique",
  FC_transition: "Transition de classe fonctionnelle (legitime)",
  Unexplained: "Inexplique (a investiguer)",
};

const TOPO_LABELS_FR: Record<TopologyKey, string> = {
  Bretelle: "Bretelle",
  Carrefour: "Carrefour",
  Continuite: "Continuite segment",
};

const TOPO_HINT: Record<TopologyKey, string> = {
  Bretelle: "Au moins une bretelle (RAMP=Y) est incidente a ce noeud.",
  Carrefour: "Au moins 3 arcs incidents (carrefour) ou rond-point detecte.",
  Continuite:
    "1 entrant + 1 sortant, pas de bretelle ni de rond-point — discontinuite en plein segment, suspect.",
};

const NARRATIVES_FR: Record<CauseKey, string> = {
  FCD_TV_cliff:
    "Discontinuite VL reposant sur une falaise des donnees FCD (ratio TMJO VL min/max eleve).",
  FCD_PL_cliff:
    "Discontinuite PL reposant sur une falaise des donnees FCD PL (ratio TMJO PL min/max eleve).",
  Coverage_gap:
    "Capteurs absents ou trop espaces : la couverture FCD est lacunaire autour du noeud.",
  Distance_anomaly:
    "Distance inter-noeuds anormale par rapport aux voisins, suggerant un decoupage du graphe deficient.",
  RAMP_asymmetry:
    "Bretelle presente uniquement d'un cote du noeud (entrant XOR sortant).",
  ROUNDABOUT_asymmetry:
    "Rond-point detecte d'un seul cote : la modelisation du carrefour est asymetrique.",
  FC_transition:
    "Changement attendu de classe fonctionnelle (FC) entre amont et aval : la rupture est legitime.",
  Unexplained:
    "Aucun signal explicatif n'a ete declenche : noeud a investiguer manuellement.",
};

const INPUT_ORDER = [
  "TMJOFCDTV",
  "TMJOFCDPL",
  "functional_class",
  "avg_distance_before_m",
  "avg_min_distance_m",
  "truck_avg_distance_before_m",
];

const INPUT_LABELS_FR: Record<string, string> = {
  TMJOFCDTV: "Trafic VL (TMJO FCD VL)",
  TMJOFCDPL: "Trafic PL (TMJO FCD PL)",
  functional_class: "Classe fonctionnelle (FC)",
  avg_distance_before_m: "Distance moyenne avant (m)",
  avg_min_distance_m: "Distance minimale (m)",
  truck_avg_distance_before_m: "Distance moyenne PL avant (m)",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtFR(n: number | null | undefined): string {
  if (n === null || n === undefined || !isFinite(Number(n))) return "—";
  return NF_FR.format(Math.round(Number(n)));
}

function fmtFRdec(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || !isFinite(Number(n))) return "—";
  return Number(n).toLocaleString("fr-FR", {
    maximumFractionDigits: d,
    minimumFractionDigits: 0,
  });
}

function tierLabel(t: unknown): string {
  return t === "red" ? "Rouge" : "Orange";
}

function fmtCellValue(k: string, v: unknown): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  if (k === "functional_class") return String(Math.round(n));
  if (k && k.endsWith("_m")) return fmtFRdec(n, 1);
  return fmtFR(n);
}

function fmtDriverExtreme(k: string, score: DriverScore | undefined): string {
  if (!score) return "";
  if (k === "functional_class") {
    const lo = score.min != null ? Math.round(Number(score.min)) : "?";
    const hi = score.max != null ? Math.round(Number(score.max)) : "?";
    return `${lo} → ${hi}`;
  }
  if (typeof score.ratio === "number" && isFinite(score.ratio))
    return "x" + fmtFRdec(score.ratio, 1);
  if (typeof score.delta === "number") return "Δ" + fmtFR(score.delta);
  return "";
}

function parseMaybeJson<T>(v: unknown, fallback: T): T {
  if (typeof v === "string") {
    try {
      return JSON.parse(v) as T;
    } catch {
      return fallback;
    }
  }
  if (v == null) return fallback;
  return v as T;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface NodePanelProps {
  feature: SelectedNode;
  onClose: () => void;
  onCopyNodeId: (nid: string) => void;
}

export function NodePanel({
  feature,
  onClose,
  onCopyNodeId,
}: NodePanelProps) {
  const props = feature.properties;
  const cause = (props.principal_cause as CauseKey) || "Unexplained";
  const tier = props.tier;
  const topo = (props.topology as TopologyKey) || "Carrefour";
  const color = PALETTE[cause] || "#999";
  const topoColor = TOPO_PALETTE[topo] || "#4682B4";
  const lat =
    typeof props.lat === "number"
      ? (props.lat as number)
      : feature.coords[1];
  const lon =
    typeof props.lon === "number"
      ? (props.lon as number)
      : feature.coords[0];

  const drivers = parseMaybeJson<string[]>(props.drivers, []);
  const scores = parseMaybeJson<Record<string, DriverScore>>(
    props.driver_scores,
    {},
  );
  const edgesIn = parseMaybeJson<EdgeRecord[]>(props.edges_in, []);
  const edgesOut = parseMaybeJson<EdgeRecord[]>(props.edges_out, []);
  const allEdges = (edgesIn || []).concat(edgesOut || []);

  const narrativeText =
    typeof props.narrative === "string" &&
    (props.narrative as string).length > 0
      ? (props.narrative as string)
      : NARRATIVES_FR[cause] || "";

  const sortedDrivers = drivers.slice().sort((a, b) => {
    const ra = scores[a]?.rank ?? 999;
    const rb = scores[b]?.rank ?? 999;
    return ra - rb;
  });
  const topDrivers = sortedDrivers.slice(0, 3);
  const extraDrivers = sortedDrivers.length - topDrivers.length;
  const driverSet = new Set(drivers);

  const osmHref =
    lat != null && lon != null
      ? `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=18/${lat}/${lon}`
      : "https://www.openstreetmap.org/";

  const tierIsRed = tier === "red";
  const nodeIdStr = String(props.node_id ?? "");

  const rankBg = ["#2A1414", "#2A1F0E", "#2A230E"];
  const rankBorder = ["#E41A1C", "#FF7F00", "#FFB000"];
  const rankBadgeBg = ["#E41A1C", "#FF7F00", "#FFB000"];
  const rankBadgeFg = ["#fff", "#1A0F00", "#1A1300"];

  return (
    <div
      className="flex flex-col h-full text-[#E6E6E6]"
      style={{
        fontFamily: "'Inter', system-ui, sans-serif",
        fontSize: "11.5px",
        lineHeight: 1.45,
      }}
    >
      <div
        className="flex items-center justify-between gap-2 px-3 py-2 border-b"
        style={{ borderColor: "#2A2F36" }}
      >
        <div className="min-w-0">
          <div
            className="font-bold text-[#E6E6E6] truncate"
            style={{ fontSize: "13px" }}
            title={`Nœud ${nodeIdStr}`}
          >
            Nœud {nodeIdStr}
          </div>
          <div
            className="text-[#9AA0A6] uppercase tracking-wide mt-0.5"
            style={{ fontSize: "9.5px", letterSpacing: "0.5px" }}
          >
            {fmtFRdec(lat, 5)}, {fmtFRdec(lon, 5)}
          </div>
        </div>
        <span
          className="inline-block px-2 py-[2px] rounded-full font-bold uppercase whitespace-nowrap"
          style={{
            fontSize: "9px",
            letterSpacing: "0.5px",
            background: tierIsRed ? "#5A1518" : "#4A2E0E",
            color: tierIsRed ? "#FF8E92" : "#FFC58A",
            border: `1px solid ${tierIsRed ? "#E41A1C" : "#FF7F00"}`,
          }}
        >
          {tierLabel(tier)}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 ml-1 w-7 h-7 inline-flex items-center justify-center rounded text-[#9AA0A6] hover:text-[#E6E6E6] hover:bg-[rgba(255,255,255,0.06)] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FFB000]"
          aria-label="Fermer le panneau"
          title="Fermer (Echap)"
        >
          <X size={16} />
        </button>
      </div>

      <section
        className="px-3 py-2.5 border-b"
        style={{ borderColor: "#2A2F36" }}
      >
        <h4
          className="m-0 mb-1.5 font-semibold uppercase text-[#9AA0A6]"
          style={{ fontSize: "9.5px", letterSpacing: "0.8px" }}
        >
          Flux
        </h4>
        <div className="grid grid-cols-3 gap-1.5">
          <FluxCell label="Entrant" value={`${fmtFR(props.flow_in as number)} v/j`} />
          <FluxCell label="Sortant" value={`${fmtFR(props.flow_out as number)} v/j`} />
          <FluxCell
            label="Écart"
            value={`${fmtFR(props.ecart as number)} v/j`}
            valueColor="#FF8E92"
            bold
          />
        </div>
        <div
          className="text-[#9AA0A6] mt-1.5"
          style={{ fontSize: "9.5px" }}
        >
          n_in = {String(props.n_in ?? "—")} · n_out ={" "}
          {String(props.n_out ?? "—")}
        </div>
      </section>

      <section
        className="px-3 py-2.5 border-b"
        style={{ borderColor: "#2A2F36" }}
      >
        <h4
          className="m-0 mb-1.5 font-semibold uppercase text-[#9AA0A6]"
          style={{ fontSize: "9.5px", letterSpacing: "0.8px" }}
        >
          Cause détectée
        </h4>
        <div
          className="flex items-center gap-2 rounded px-2.5 py-2"
          style={{
            background: color,
            color: "#fff",
            fontWeight: 700,
            fontSize: "14px",
            textShadow: "0 1px 2px rgba(0,0,0,0.45)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          <span
            className="shrink-0 rounded-full"
            style={{
              width: 12,
              height: 12,
              background: "rgba(255,255,255,0.85)",
              boxShadow: "0 0 0 2px rgba(0,0,0,0.25)",
            }}
          />
          <span className="truncate">
            {CAUSE_LABELS_FR[cause] || cause}
          </span>
        </div>
        <p
          className="text-[#BFC4CA] mt-2 leading-relaxed"
          style={{ fontSize: "11.5px" }}
        >
          {narrativeText}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span
            className="uppercase text-[#9AA0A6]"
            style={{ fontSize: "9.5px", letterSpacing: "0.6px" }}
          >
            Topologie :
          </span>
          <span
            className="inline-flex items-center gap-1.5 rounded-full font-semibold text-white"
            style={{
              padding: "3px 8px",
              fontSize: "10.5px",
              background: topoColor,
            }}
          >
            <span
              className="rounded-full"
              style={{
                width: 6,
                height: 6,
                background: "rgba(255,255,255,0.85)",
              }}
            />
            {TOPO_LABELS_FR[topo] || topo}
          </span>
          <div
            className="basis-full text-[#9AA0A6] leading-snug"
            style={{ fontSize: "10px" }}
          >
            {TOPO_HINT[topo] || ""}
          </div>
        </div>
      </section>

      <section
        className="px-3 py-2.5 border-b"
        style={{ borderColor: "#2A2F36" }}
      >
        <h4
          className="m-0 mb-1.5 font-semibold uppercase text-[#9AA0A6]"
          style={{ fontSize: "9.5px", letterSpacing: "0.8px" }}
        >
          Causes principales
        </h4>
        {topDrivers.length === 0 ? (
          <div className="text-[#9AA0A6]" style={{ fontSize: "10.5px" }}>
            Aucun driver statistique déclenché — cause attribuée par
            topologie.
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {topDrivers.map((k, i) => {
              const score = scores[k] || {};
              const extreme = fmtDriverExtreme(k, score);
              return (
                <div
                  key={k}
                  className="flex items-center gap-2 rounded px-2 py-1"
                  style={{
                    background: rankBg[i],
                    border: `1px solid ${rankBorder[i]}`,
                    fontSize: "10.5px",
                  }}
                >
                  <span
                    className="inline-flex items-center justify-center rounded-full font-bold shrink-0"
                    style={{
                      width: 18,
                      height: 18,
                      fontSize: "9px",
                      background: rankBadgeBg[i],
                      color: rankBadgeFg[i],
                    }}
                  >
                    #{i + 1}
                  </span>
                  <span className="flex-1 text-[#E6E6E6] font-medium truncate">
                    {INPUT_LABELS_FR[k] || k}
                  </span>
                  <span
                    className="font-bold tabular-nums"
                    style={{ color: "#FFB7B7" }}
                  >
                    {extreme}
                  </span>
                </div>
              );
            })}
            {extraDrivers > 0 && (
              <div
                className="text-[#9AA0A6] italic mt-1"
                style={{ fontSize: "10px" }}
              >
                + {extraDrivers} autre{extraDrivers > 1 ? "s" : ""} facteur
                {extraDrivers > 1 ? "s" : ""} détecté
                {extraDrivers > 1 ? "s" : ""}
              </div>
            )}
          </div>
        )}
      </section>

      {allEdges.length > 0 && (
        <section
          className="px-3 py-2.5 border-b"
          style={{ borderColor: "#2A2F36" }}
        >
          <h4
            className="m-0 mb-1.5 font-semibold uppercase text-[#9AA0A6]"
            style={{ fontSize: "9.5px", letterSpacing: "0.8px" }}
          >
            Valeurs par segment
          </h4>
          <div className="overflow-x-auto -mx-1 px-1">
            <table
              className="w-full border-collapse"
              style={{ fontSize: "10.5px" }}
            >
              <thead>
                <tr>
                  <th
                    className="text-left font-semibold"
                    style={{
                      padding: "3px 5px",
                      minWidth: 110,
                      background: "#14171A",
                      color: "#fff",
                      borderBottom: "1px solid #2a2f36",
                      fontSize: "11px",
                      whiteSpace: "nowrap",
                    }}
                  >
                    Variable
                  </th>
                  {allEdges.map((e, i) => {
                    const lbl = e.label || "";
                    const isE = lbl.startsWith("E");
                    return (
                      <th
                        key={`hdr-${i}-${lbl}`}
                        className="text-right font-semibold tabular-nums"
                        style={{
                          padding: "3px 5px",
                          background: isE ? "#1e3a5f" : "#5f1e3a",
                          color: isE ? "#cfe0ff" : "#ffcfe0",
                          borderBottom: "1px solid #2a2f36",
                          fontSize: "11px",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {lbl}
                      </th>
                    );
                  })}
                </tr>
                <tr>
                  <th
                    className="text-left"
                    style={{
                      padding: "3px 5px",
                      background: "#14171A",
                      color: "#cfd6df",
                      borderBottom: "1px solid #2a2f36",
                      fontSize: "10px",
                      fontWeight: 400,
                      whiteSpace: "nowrap",
                    }}
                  >
                    JOr (v/j)
                  </th>
                  {allEdges.map((e, i) => {
                    const lbl = e.label || "";
                    const isE = lbl.startsWith("E");
                    return (
                      <th
                        key={`jor-${i}-${lbl}`}
                        className="text-right tabular-nums"
                        style={{
                          padding: "3px 5px",
                          background: isE ? "#14202d" : "#2d1420",
                          color: isE ? "#9fb5d4" : "#d49fb5",
                          borderBottom: "1px solid #2a2f36",
                          fontSize: "10px",
                          fontWeight: 400,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {fmtFR(e.JOr ?? e.TVr ?? null)}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {INPUT_ORDER.map((k) => {
                  const isDriver = driverSet.has(k);
                  const label = INPUT_LABELS_FR[k] || k;
                  return (
                    <tr key={k}>
                      <td
                        className="text-left"
                        style={{
                          padding: "2.5px 5px",
                          borderBottom: "1px solid #1f2329",
                          background: isDriver ? "#2a1414" : undefined,
                          color: isDriver ? "#FFB7B7" : "#d4d4d8",
                          fontWeight: isDriver ? 600 : 500,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {label}
                      </td>
                      {allEdges.map((e, i) => {
                        const v =
                          e.inputs && e.inputs[k] !== undefined
                            ? e.inputs[k]
                            : null;
                        return (
                          <td
                            key={`${k}-${i}`}
                            className="text-right tabular-nums"
                            style={{
                              padding: "2.5px 5px",
                              borderBottom: "1px solid #1f2329",
                              background: isDriver ? "#2a1414" : undefined,
                              color: isDriver ? "#FFB7B7" : "#9ca3af",
                              fontWeight: isDriver ? 600 : 400,
                              whiteSpace: "nowrap",
                            }}
                          >
                            {fmtCellValue(k, v)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="flex-1" />

      <div
        className="sticky bottom-0 left-0 right-0 flex gap-1.5 px-3 py-2.5 bg-[#1B1F23] border-t"
        style={{ borderColor: "#2A2F36" }}
      >
        <button
          type="button"
          onClick={() => onCopyNodeId(nodeIdStr)}
          className="flex-1 rounded text-[#E6E6E6] hover:text-[#22d3ee] hover:border-[#22d3ee] transition-colors text-center cursor-pointer"
          style={{
            padding: "6px 8px",
            fontSize: "11px",
            background: "#14171A",
            border: "1px solid #2A2F36",
            fontWeight: 500,
          }}
        >
          Copier ID
        </button>
        <a
          href={osmHref}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 rounded text-[#E6E6E6] hover:text-[#22d3ee] hover:border-[#22d3ee] transition-colors text-center no-underline"
          style={{
            padding: "6px 8px",
            fontSize: "11px",
            background: "#14171A",
            border: "1px solid #2A2F36",
            fontWeight: 500,
          }}
        >
          Voir sur OSM
        </a>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FluxCell — sous-composant utilise uniquement par NodePanel
// ---------------------------------------------------------------------------

function FluxCell({
  label,
  value,
  valueColor,
  bold,
}: {
  label: string;
  value: string;
  valueColor?: string;
  bold?: boolean;
}) {
  return (
    <div
      className="rounded"
      style={{ background: "#14171A", padding: "5px 7px" }}
    >
      <div
        className="uppercase text-[#9AA0A6]"
        style={{ fontSize: "9px", letterSpacing: "0.4px" }}
      >
        {label}
      </div>
      <div
        className="tabular-nums"
        style={{
          fontSize: "12.5px",
          fontWeight: bold ? 700 : 600,
          color: valueColor ?? "#E6E6E6",
          marginTop: 1,
        }}
      >
        {value}
      </div>
    </div>
  );
}
