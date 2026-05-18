/**
 * map-style.ts — Maplibre raster basemap styles using free OSM tile providers.
 *
 * Two themes via CartoDB basemaps (free for non-commercial / attribution
 * required — see https://github.com/CartoDB/basemap-styles):
 *   - dark  → "dark_all"           (Dark Matter)
 *   - light → "voyager_nolabels"   (clean light, neutral)
 *
 * Both are OSM data, no token required, 100 % free.
 */

import type { StyleSpecification } from "maplibre-gl";

const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>';

function buildRasterStyle(tileUrlTemplate: string): StyleSpecification {
  return {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      basemap: {
        type: "raster",
        tiles: [
          tileUrlTemplate.replace("{s}", "a"),
          tileUrlTemplate.replace("{s}", "b"),
          tileUrlTemplate.replace("{s}", "c"),
          tileUrlTemplate.replace("{s}", "d"),
        ],
        tileSize: 256,
        attribution: OSM_ATTRIBUTION,
        maxzoom: 19,
      },
    },
    layers: [
      {
        id: "basemap-raster",
        type: "raster",
        source: "basemap",
        minzoom: 0,
        maxzoom: 22,
      },
    ],
  };
}

const DARK_TILE = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png";
const LIGHT_TILE = "https://{s}.basemaps.cartocdn.com/voyager_nolabels/{z}/{x}/{y}.png";

export function getMapStyle(theme: "dark" | "light"): StyleSpecification {
  return buildRasterStyle(theme === "dark" ? DARK_TILE : LIGHT_TILE);
}

/** Default style: dark, matching the app's default theme. */
export const defaultMapStyle: StyleSpecification = getMapStyle("dark");
