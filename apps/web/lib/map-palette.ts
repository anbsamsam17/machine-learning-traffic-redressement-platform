/**
 * map-palette.ts — YlOrRd-like graduated palette for traffic volumes (TVr).
 *
 * 7 paliers (P3 §1.5) — increasing volume = warmer color.
 * Bins are inclusive-lower / exclusive-upper, last bin catches everything above.
 *
 * Colors picked from ColorBrewer YlOrRd / OrRd ramps and adjusted for the
 * project dark theme (slightly desaturated low end so light segments don't
 * dominate when mixed with the dark Carto basemap).
 */

export interface PaletteStop {
  /** Lower bound (veh/j) — segment with TVr >= min and < next stop's min */
  min: number;
  label: string;
  color: string;
}

/**
 * Public stops, ordered from low to high TVr.
 * Used by both the layer paint expression and the legend.
 */
export const TVR_STOPS: ReadonlyArray<PaletteStop> = [
  { min: 0,     label: "< 500",          color: "#fff3b0" }, // pale yellow
  { min: 500,   label: "500 – 1 000",    color: "#fed976" },
  { min: 1000,  label: "1 000 – 2 000",  color: "#feb24c" },
  { min: 2000,  label: "2 000 – 4 000",  color: "#fd8d3c" },
  { min: 4000,  label: "4 000 – 8 000",  color: "#fc4e2a" },
  { min: 8000,  label: "8 000 – 15 000", color: "#e31a1c" },
  { min: 15000, label: "> 15 000",       color: "#800026" }, // deep red
] as const;

/**
 * Lookup the color for a numeric TVr value.
 * Defensive: returns the lowest stop color for NaN / negative input.
 */
export function getColorForTVr(value: number): string {
  if (typeof value !== "number" || !isFinite(value) || value < 0) {
    return TVR_STOPS[0].color;
  }
  let color = TVR_STOPS[0].color;
  for (const stop of TVR_STOPS) {
    if (value >= stop.min) color = stop.color;
    else break;
  }
  return color;
}

/**
 * Build a Maplibre `step` paint expression keyed on the `TVr` property.
 * Format: ["step", input, default, stop1, color1, stop2, color2, ...]
 */
export function buildTvrStepExpression(): unknown[] {
  const expr: unknown[] = [
    "step",
    ["to-number", ["get", "TVr"], 0],
    TVR_STOPS[0].color, // values < first threshold (none, since first.min === 0)
  ];
  for (let i = 1; i < TVR_STOPS.length; i++) {
    expr.push(TVR_STOPS[i].min, TVR_STOPS[i].color);
  }
  return expr;
}

/**
 * Compute line width as a function of zoom + TVr (heavier segments stay
 * visible when zoomed out, fine streets get thinner).
 */
export function buildLineWidthExpression(): unknown[] {
  // interpolate(linear, zoom, z1, w1, z2, w2)
  // and inside, scale by TVr magnitude.
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    8, [
      "interpolate", ["linear"], ["to-number", ["get", "TVr"], 0],
      0, 0.6,
      2000, 1.0,
      10000, 1.8,
    ],
    13, [
      "interpolate", ["linear"], ["to-number", ["get", "TVr"], 0],
      0, 1.2,
      2000, 2.2,
      10000, 4.5,
    ],
    17, [
      "interpolate", ["linear"], ["to-number", ["get", "TVr"], 0],
      0, 2.0,
      2000, 4.0,
      10000, 8.0,
    ],
  ];
}
