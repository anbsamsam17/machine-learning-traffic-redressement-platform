"use client";

/**
 * UploadMappingFlow — shared upload + auto-mapping + preview component.
 *
 * Used by `donnees/page.tsx` (TV/PL) and reusable for any pipeline that
 * follows the upload → auto-map → validate → preview pattern.
 *
 * Compteurs follows a different shape (sens, missing actions, lon/lat)
 * and stays in its own page; only the DropZone primitive is shared.
 */
import {
  useState,
  useCallback,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import {
  FileSpreadsheet,
  Wand2,
  Table2,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";
import { DropZone } from "@/components/upload/drop-zone";
import {
  ColumnMapper,
  type ColumnMapping,
} from "@/components/mapping/column-mapper";
import { Button } from "@/components/ui/button";
import { StatCard } from "@/components/ui/stat-card";
import { useAppStore } from "@/lib/store";
import { apiClient, ApiError } from "@/lib/api";
import { useUploadFile } from "@/lib/hooks";

export interface UploadMappingFlowProps {
  /** Pipeline mode — passed to /api/upload */
  mode: "TV" | "PL" | "carte" | "compteurs";
  /** All target columns the mapping UI will display */
  targetColumns: string[];
  /** Subset of targetColumns flagged as critical (highlighted) */
  criticalColumns: string[];
  /** File types accepted by the dropzone */
  acceptedFileTypes?: Record<string, string[]>;
  /** DropZone copy */
  dropLabel?: string;
  dropDescription?: string;
  /** Called once validation succeeds — typically navigates to the next step */
  onValidated?: (sessionId: string, mapping: Record<string, string | null>) => void;
  /** Render slot above the upload card */
  headerSlot?: ReactNode;
}

interface UploadResponse {
  session_id: string;
  filename?: string;
  rows: number;
  columns?: string[];
  preview: Record<string, unknown>[];
}

interface AutoMapResponse {
  source_columns: string[];
  mappings: { target: string; source: string | null; confidence: string }[];
}

interface ValidateResponse {
  rows: number;
  columns: string[];
  preview: Record<string, unknown>[];
  missing_critical?: string[];
  warnings?: string[];
}

const CONFIDENCE_SCORE: Record<string, number> = {
  exact: 100,
  synonym: 85,
  fuzzy: 70,
  missing: 0,
};

export function UploadMappingFlow({
  mode,
  targetColumns,
  criticalColumns,
  acceptedFileTypes,
  dropLabel = "Deposez votre fichier de donnees",
  dropDescription = "CSV, Excel (.xlsx) ou GeoJSON",
  onValidated,
  headerSlot,
}: UploadMappingFlowProps) {
  const { setFileName } = useAppStore();
  const uploadMut = useUploadFile<UploadResponse>();
  const [file, setFile] = useState<File | null>(null);
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [step, setStep] = useState<"upload" | "mapping" | "preview">("upload");
  const [isAutoMapping, setIsAutoMapping] = useState(false);
  const [stepComplete, setStepComplete] = useState(false);

  const mappedCriticalCount = useMemo(
    () =>
      mappings.filter(
        (m) => m.source !== null && criticalColumns.includes(m.target)
      ).length,
    [mappings, criticalColumns]
  );

  const unmappedCritical = useMemo(
    () =>
      criticalColumns.filter(
        (col) => !mappings.find((m) => m.target === col && m.source !== null)
      ),
    [mappings, criticalColumns]
  );

  const handleFile = useCallback(
    async (f: File) => {
      setFile(f);
      setFileName(f.name);
      setIsAutoMapping(true);

      try {
        // 1. Upload via TanStack mutation
        const uploadData = await uploadMut.mutateAsync({
          file: f,
          path: "/api/upload",
          extra: { mode },
        });
        const sessionId = uploadData.session_id;
        useAppStore.getState().setSessionId(sessionId);

        // 2. Auto-mapping
        const mapData = await apiClient.post<AutoMapResponse>(
          "/api/mapping/auto",
          { session_id: sessionId }
        );
        const srcCols = mapData.source_columns ?? [];
        setSourceColumns(srcCols);

        const autoMappings: ColumnMapping[] = (mapData.mappings ?? []).map(
          (m) => ({
            target: m.target,
            source: m.source,
            confidence: CONFIDENCE_SCORE[m.confidence] ?? 0,
          })
        );
        setMappings(autoMappings);
        setPreviewRows(uploadData.preview ?? []);
        setStep("mapping");
        toast.success(
          `Fichier charge : ${uploadData.rows} lignes, ${srcCols.length} colonnes`
        );

        const missingCritical = criticalColumns.filter(
          (col) =>
            !(mapData.mappings ?? []).find(
              (m) => m.target === col && m.source !== null
            )
        );
        if (missingCritical.length > 0) {
          toast.warning(
            `${missingCritical.length} colonne(s) critique(s) non mappee(s) : ${missingCritical.join(", ")}`
          );
        }
      } catch (err) {
        const detail = err instanceof ApiError ? err.detail : String(err);
        // eslint-disable-next-line no-console
        console.error("Auto-mapping error:", detail);
        toast.error(
          "Erreur lors de l'auto-mapping. Verifiez que le backend est accessible."
        );
        // Fallback: empty mappings so user can map manually
        setSourceColumns([]);
        setMappings(
          targetColumns.map((target) => ({ target, source: null, confidence: 0 }))
        );
        setStep("mapping");
      } finally {
        setIsAutoMapping(false);
      }
    },
    [mode, criticalColumns, targetColumns, setFileName, uploadMut]
  );

  const handleClear = useCallback(() => {
    setFile(null);
    setSourceColumns([]);
    setMappings([]);
    setPreviewRows([]);
    setStep("upload");
    setStepComplete(false);
  }, []);

  const handleValidate = useCallback(async () => {
    const mapped = mappings.filter((m) => m.source !== null);
    if (mapped.length < 5) {
      toast.error("Mappez au moins 5 colonnes pour continuer");
      return;
    }

    if (unmappedCritical.length > 0) {
      toast.warning(
        `Attention : ${unmappedCritical.length} colonne(s) critique(s) non mappee(s). L'entrainement risque d'echouer.`
      );
    }

    const currentSessionId = useAppStore.getState().sessionId;
    if (!currentSessionId) {
      toast.error("Pas de session active. Re-importez le fichier.");
      return;
    }

    const mappingPayload: Record<string, string | null> = {};
    mappings.forEach((m) => {
      mappingPayload[m.target] = m.source;
    });

    try {
      const data = await apiClient.post<ValidateResponse>(
        "/api/mapping/validate",
        {
          session_id: currentSessionId,
          mapping: mappingPayload,
          territory: "default",
        }
      );
      setPreviewRows(data.preview ?? []);
      setStep("preview");
      if (data.missing_critical?.length) {
        toast.warning(
          `Colonnes critiques manquantes : ${data.missing_critical.join(", ")}`
        );
      }
      if (data.warnings?.length) {
        data.warnings.forEach((w) => toast.warning(w));
      }
      toast.success(
        `Table d'apprentissage generee : ${data.rows} lignes, ${data.columns?.length ?? 0} colonnes`
      );
      setStepComplete(true);
      onValidated?.(currentSessionId, mappingPayload);
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : String(err);
      toast.error(`Erreur validation : ${detail}`);
    }
  }, [mappings, unmappedCritical, onValidated]);

  // Cache the visible columns / count for the preview table.
  const previewColumns = useMemo(
    () => (previewRows[0] ? Object.keys(previewRows[0]) : []),
    [previewRows]
  );

  return (
    <div className="space-y-5">
      {headerSlot}

      {/* Upload card */}
      <div className="surface-elevated p-5">
        <div className="flex items-center gap-2 mb-4">
          <FileSpreadsheet
            size={16}
            className="text-accent"
            aria-hidden="true"
          />
          <h3 className="text-sm font-semibold text-text">Fichier source</h3>
          {isAutoMapping && (
            <span className="text-xs text-text-muted ml-2">
              Auto-mapping en cours...
            </span>
          )}
        </div>
        <DropZone
          file={file}
          onFile={handleFile}
          onClear={handleClear}
          accept={acceptedFileTypes}
          label={dropLabel}
          description={dropDescription}
        />
      </div>

      {/* Mapping card */}
      {step === "mapping" && (
        <div className="surface-elevated p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Table2 size={16} className="text-accent" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-text">
                Mapping des colonnes
              </h3>
            </div>
            <Button
              variant="primary"
              size="sm"
              onClick={handleValidate}
              icon={<Wand2 size={14} />}
            >
              Valider et generer la table
            </Button>
          </div>

          {unmappedCritical.length > 0 && (
            <div
              className="flex items-start gap-2 p-3 mb-4 rounded border border-warning/30 bg-warning/5"
              role="status"
            >
              <AlertTriangle
                size={14}
                className="text-warning flex-shrink-0 mt-0.5"
                aria-hidden="true"
              />
              <div className="text-xs">
                <span className="text-warning font-semibold">
                  {unmappedCritical.length}/{criticalColumns.length} colonnes
                  critiques non mappees
                </span>
                <p className="text-text-muted mt-1 font-mono">
                  {unmappedCritical.join(", ")}
                </p>
              </div>
            </div>
          )}

          <ColumnMapper
            targetColumns={targetColumns}
            sourceColumns={sourceColumns}
            criticalColumns={criticalColumns}
            initialMappings={mappings}
            onMappingsChange={setMappings}
          />
        </div>
      )}

      {/* Preview card */}
      {step === "preview" && previewRows.length > 0 && (
        <div className="surface-elevated p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Table2 size={16} className="text-success" aria-hidden="true" />
            <h3 className="text-sm font-semibold text-text">
              Apercu de la table d&apos;apprentissage
            </h3>
            {stepComplete && (
              <span className="ml-auto inline-flex items-center gap-1.5 px-2 h-6 rounded text-[11px] font-medium bg-success/10 border border-success/30 text-success">
                <CheckCircle2 size={11} aria-hidden="true" />
                Etape completee
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Lignes" value={previewRows.length} />
            <StatCard
              label="Mappees"
              value={`${mappings.filter((m) => m.source).length}/${targetColumns.length}`}
            />
            <StatCard
              label="Critiques"
              value={`${mappedCriticalCount}/${criticalColumns.length}`}
              trend={
                mappedCriticalCount === criticalColumns.length ? "up" : "down"
              }
            />
            <StatCard
              label="Confiance"
              value={`${Math.round(
                mappings.filter((m) => m.source).reduce((s, m) => s + m.confidence, 0) /
                  Math.max(mappings.filter((m) => m.source).length, 1)
              )}%`}
            />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border">
                  {previewColumns.slice(0, 8).map((col) => (
                    <th
                      key={col}
                      className="px-2 py-1.5 text-left text-text-muted font-medium"
                    >
                      <span className="font-mono">{col}</span>
                      {criticalColumns.includes(col) && (
                        <span
                          className="text-warning ml-1"
                          aria-label="colonne critique"
                        >
                          *
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row, i) => (
                  <tr
                    key={i}
                    className="border-b border-border/40 hover:bg-bg-subtle/40 transition-colors"
                  >
                    {Object.values(row)
                      .slice(0, 8)
                      .map((val, j) => (
                        <td
                          key={j}
                          className="px-2 py-1.5 text-text font-mono tabular-nums"
                        >
                          {String(val)}
                        </td>
                      ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-text-subtle">
            Affichage des 8 premieres colonnes sur {previewColumns.length}{" "}
            colonnes totales.
          </p>
        </div>
      )}
    </div>
  );
}
