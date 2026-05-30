"use client";

import { memo } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, FolderOpen, X, XCircle } from "lucide-react";

// ---------------------------------------------------------------------------
// ValidityBadge — affiche structure valide / liste des fichiers manquants
// ---------------------------------------------------------------------------
// Extrait du render de app/carte/page.tsx (etait redeclaree a chaque render).
// Memoisee pour eviter les re-renders inutiles quand le parent rerendert.
// ---------------------------------------------------------------------------

export interface ValidityBadgeProps {
  valid: boolean | null;
  missing: string[];
}

export const ValidityBadge = memo(function ValidityBadge({
  valid,
  missing,
}: ValidityBadgeProps) {
  if (valid === null) return null;
  return valid ? (
    <div className="flex items-center gap-1.5 text-emerald-400 text-xs mt-1.5">
      <CheckCircle2 size={14} />
      <span>Structure valide</span>
    </div>
  ) : (
    <div className="flex items-center gap-1.5 text-red-400 text-xs mt-1.5">
      <XCircle size={14} />
      <span>Manquant : {missing.join(", ")}</span>
    </div>
  );
});

// ---------------------------------------------------------------------------
// FolderBrowseButton — dropzone "browse folder" avec etat charge
// ---------------------------------------------------------------------------

export interface FolderBrowseButtonProps {
  folderName: string | null;
  isUploading: boolean;
  onClear: () => void;
  onClick: () => void;
  label: string;
  description: string;
}

export const FolderBrowseButton = memo(function FolderBrowseButton({
  folderName,
  isUploading,
  onClear,
  onClick,
  label,
  description,
}: FolderBrowseButtonProps) {
  if (folderName) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="flex items-center gap-3 p-3.5 rounded-xl border border-indigo-500/20 bg-indigo-500/5"
      >
        <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 flex-shrink-0">
          <FolderOpen size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-slate-200 truncate">{folderName}</p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="p-1.5 rounded-lg hover:bg-red-500/10 text-slate-400 hover:text-red-400 transition-colors"
        >
          <X size={14} />
        </button>
      </motion.div>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isUploading}
      className="w-full flex flex-col items-center justify-center gap-3 p-8 rounded-2xl border-2 border-dashed border-white/[0.08] hover:border-indigo-500/40 bg-slate-900/30 hover:bg-indigo-500/5 transition-all duration-300 cursor-pointer group disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 group-hover:bg-indigo-500/20 transition-colors">
        <FolderOpen size={22} />
      </div>
      <div className="text-center">
        <p className="text-xs font-medium text-slate-200">{label}</p>
        <p className="text-[10px] text-slate-400 mt-1">{description}</p>
      </div>
    </button>
  );
});
