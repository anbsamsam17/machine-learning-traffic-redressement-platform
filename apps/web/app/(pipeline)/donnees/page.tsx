"use client";

import { UploadMappingFlow } from "@/components/pipeline/upload-mapping-flow";
import { useAppStore } from "@/lib/store";

// Real 36 target columns from column_mapper.py (35 + geometry).
const TARGET_COLUMNS = [
  "Type", "Identifiant", "Commune", "Route", "PRD",
  "MJA TV 2023", "MJA PL 2023", "MJA TV 2024", "MJA PL 2024",
  "MJA TV 2025", "MJA PL 2025",
  "TMJABCTV", "TMJABCPL", "Annee", "Road", "TMJAVL", "TMJAPL", "TMJATV",
  "TxPen", "TxPenPL", "variabilite_FCD",
  "car_count", "car_average_speed_kmh", "car_average_distance_km",
  "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
  "REF_IN_ID", "NREF_IN_ID", "TUNNEL", "status", "RAMP", "ROUNDABOUT",
  "ST_NAME", "flag_comptage", "geometry",
];

// Critical columns required for model training (from df_builder.py).
const CRITICAL_COLS = [
  "TMJATV",
  "TMJAPL",
  "TxPen",
  "car_average_distance_km",
  "car_average_speed_kmh",
  "truck_min_average_distance_km",
  "truck_average_speed_kmh",
];

const ACCEPTED_FILE_TYPES = {
  "application/json": [".geojson", ".json"],
  "text/csv": [".csv"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.ms-excel": [".xls"],
};

export default function DonneesPage() {
  const { mode } = useAppStore();
  const apiMode = mode === "pl" ? "PL" : "TV";

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <h2 className="text-2xl font-semibold text-text">Donnees</h2>
        <p className="text-sm text-text-muted">
          Importez votre fichier de donnees brutes et configurez le mapping
          des colonnes vers les {TARGET_COLUMNS.length} colonnes standard.
        </p>
      </div>

      <UploadMappingFlow
        mode={apiMode}
        targetColumns={TARGET_COLUMNS}
        criticalColumns={CRITICAL_COLS}
        acceptedFileTypes={ACCEPTED_FILE_TYPES}
        dropLabel="Deposez votre fichier de donnees"
        dropDescription="CSV, Excel (.xlsx) ou GeoJSON"
      />
    </div>
  );
}
