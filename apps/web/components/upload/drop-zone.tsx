"use client";

import { useCallback, useEffect, useRef } from "react";
import { useDropzone } from "react-dropzone";
import { Upload, FileCheck, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { dropZonePulse } from "@/lib/animations/gsap";

interface DropZoneProps {
  onFile: (file: File) => void;
  file: File | null;
  onClear: () => void;
  accept?: Record<string, string[]>;
  label?: string;
  description?: string;
}

export function DropZone({
  onFile,
  file,
  onClear,
  accept = {
    "application/json": [".geojson", ".json"],
    "text/csv": [".csv"],
    "application/zip": [".zip"],
  },
  label = "Deposez votre fichier ici",
  description = "GeoJSON, CSV ou ZIP",
}: DropZoneProps) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted.length > 0) {
        onFile(accepted[0]);
      }
    },
    [onFile]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
    multiple: false,
  });

  const zoneRef = useRef<HTMLDivElement>(null);

  // M5 — subtle pulse when drag enters (border accent comes from isDragActive).
  useEffect(() => {
    if (isDragActive && zoneRef.current) {
      dropZonePulse(zoneRef.current);
    }
  }, [isDragActive]);

  if (file) {
    return (
      <div
        className="surface-elevated p-4 flex items-center gap-3"
        role="status"
        aria-live="polite"
      >
        <div className="w-9 h-9 rounded bg-success/10 flex items-center justify-center text-success shrink-0">
          <FileCheck size={18} aria-hidden="true" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-text truncate">{file.name}</p>
          <p className="text-xs text-text-muted mt-0.5 font-mono tabular-nums">
            {(file.size / 1024).toFixed(1)} Ko
          </p>
        </div>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClear();
          }}
          className="p-1.5 rounded text-text-muted hover:text-danger hover:bg-danger/10 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-label="Retirer le fichier"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>
    );
  }

  const { ref: dzRef, ...rootProps } = getRootProps();
  return (
    <div
      {...rootProps}
      ref={(el) => {
        zoneRef.current = el;
        if (typeof dzRef === "function") dzRef(el);
      }}
      className={cn(
        "relative flex flex-col items-center justify-center gap-3 px-6 py-10 rounded-md border border-dashed transition-colors cursor-pointer group",
        isDragActive
          ? "border-accent bg-accent-subtle"
          : "border-border hover:border-border-strong bg-bg-elevated"
      )}
      role="button"
      tabIndex={0}
      aria-label={label}
    >
      <input {...getInputProps()} />
      <div
        className={cn(
          "w-10 h-10 rounded-md flex items-center justify-center transition-colors",
          isDragActive
            ? "bg-accent/20 text-accent"
            : "bg-bg-subtle text-text-muted group-hover:text-accent"
        )}
      >
        <Upload size={20} aria-hidden="true" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-text">{label}</p>
        <p className="text-xs text-text-muted mt-1">{description}</p>
      </div>
    </div>
  );
}
