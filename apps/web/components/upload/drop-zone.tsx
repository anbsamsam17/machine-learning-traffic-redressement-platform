"use client";

import { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, FileCheck, X } from "lucide-react";
import { cn } from "@/lib/utils";

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

  return (
    <div className="w-full">
      <AnimatePresence mode="wait">
        {!file ? (
          <motion.div
            key="dropzone"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div
              {...getRootProps()}
              className={cn(
                "relative flex flex-col items-center justify-center gap-4 p-12 rounded-2xl border-2 border-dashed transition-all duration-300 cursor-pointer group",
                isDragActive
                  ? "border-accent bg-accent/5 neon-glow"
                  : "border-border hover:border-accent/40 bg-surface/50"
              )}
            >
              <input {...getInputProps()} />
              <motion.div
                animate={
                  isDragActive
                    ? { scale: 1.2, rotate: 5 }
                    : { scale: 1, rotate: 0 }
                }
                className={cn(
                  "w-16 h-16 rounded-2xl flex items-center justify-center transition-colors",
                  isDragActive ? "bg-accent/20 text-accent" : "bg-surface-light text-muted group-hover:text-accent"
                )}
              >
                <Upload size={28} />
              </motion.div>
              <div className="text-center">
                <p className="text-sm font-medium text-foreground">{label}</p>
                <p className="text-xs text-muted mt-1">{description}</p>
              </div>
              {isDragActive && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="absolute inset-0 rounded-2xl bg-accent/5 pointer-events-none"
                />
              )}
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="file"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="glass-light p-5 flex items-center gap-4"
          >
            <div className="w-12 h-12 rounded-xl bg-emerald-500/10 flex items-center justify-center text-emerald-400 flex-shrink-0">
              <FileCheck size={22} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">
                {file.name}
              </p>
              <p className="text-xs text-muted mt-0.5">
                {(file.size / 1024).toFixed(1)} Ko
              </p>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onClear();
              }}
              className="p-2 rounded-lg hover:bg-red-500/10 text-muted hover:text-red-400 transition-colors"
            >
              <X size={16} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
