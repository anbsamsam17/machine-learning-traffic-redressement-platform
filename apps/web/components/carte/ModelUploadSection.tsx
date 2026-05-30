"use client";

import { useRef, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import type {
  CarteModelUploadResponse,
  ModelKind,
} from "@/lib/carte/types";
import {
  FolderBrowseButton,
  ValidityBadge,
} from "@/components/carte/internals";

// ---------------------------------------------------------------------------
// ModelUploadSection — composant generique pour les 4 modes (TV/PL/HPM/HPS)
// ---------------------------------------------------------------------------
// Le parent fournit :
//  - kind            : "tv" | "pl" | "hpm" | "hps"
//  - sessionId       : null bloque l'upload (cf check backend)
//  - folderName      : nom du dossier en cours / charge
//  - isUploading     : etat upload
//  - valid / missing : badge de validite
//  - onUploadStart   : pose le folderName + start spinner
//  - onUploadSuccess : recoit la reponse backend
//  - onUploadError   : reset les flags de l'etat
//  - onClear         : reset complet
// ---------------------------------------------------------------------------

export interface ModelUploadSectionProps {
  kind: ModelKind;
  sessionId: string | null;
  folderName: string | null;
  isUploading: boolean;
  valid: boolean | null;
  missing: string[];
  label: ReactNode; // ex : "Modele TV (Trafic Vehicules)"
  icon: ReactNode;
  browseLabel: string;
  browseDescription: string;
  // Optionnel : statut "Charge" / "Non charge" affiche a cote du label (HPM/HPS)
  showLoadedBadge?: boolean;
  hint?: ReactNode; // ex : "Ajoute PM / PMmin / PMmax (v/h) a la carte"
  dimWhenEmpty?: boolean; // utilise pour HPM/HPS (opacity-70 si aucun dossier)
  onUploadStart: (folderName: string) => void;
  onUploadSuccess: (data: CarteModelUploadResponse) => void;
  onUploadError: () => void;
  onUploadFinally: () => void;
  onClear: () => void;
}

export function ModelUploadSection(props: ModelUploadSectionProps) {
  const {
    kind,
    sessionId,
    folderName,
    isUploading,
    valid,
    missing,
    label,
    icon,
    browseLabel,
    browseDescription,
    showLoadedBadge = false,
    hint,
    dimWhenEmpty = false,
    onUploadStart,
    onUploadSuccess,
    onUploadError,
    onUploadFinally,
    onClear,
  } = props;

  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;

    // Block model upload until a real FCD session exists. The backend
    // /api/carte/upload-model-folder requires a session_id created by
    // /api/upload — without it, the request hits the auth check with a
    // synthetic id and bubbles up as "Utilisateur introuvable".
    if (!sessionId) {
      toast.error(
        "Importez d'abord le fichier FCD (Etape 1) avant les modeles.",
      );
      e.target.value = "";
      return;
    }

    // Extract folder name
    const firstPath =
      (fileList[0] as File & { webkitRelativePath?: string })
        .webkitRelativePath ?? fileList[0].name;
    const rootFolder = firstPath.split("/")[0] || "dossier";

    onUploadStart(rootFolder);

    try {
      const form = new FormData();
      form.append("session_id", sessionId);
      form.append("model_type", kind);

      for (let i = 0; i < fileList.length; i++) {
        const file = fileList[i] as File & { webkitRelativePath?: string };
        const relativePath = file.webkitRelativePath ?? file.name;
        // Strip the root folder name
        const parts = relativePath.split("/");
        const strippedPath =
          parts.length > 1 ? parts.slice(1).join("/") : parts[0];
        form.append("files", file, strippedPath);
      }

      // Use apiClient.postForm so the Bearer token is attached. Raw fetch
      // here previously relied on cookies, which only worked when going
      // through the Next.js dev proxy on the same origin. With cross-origin
      // (NEXT_PUBLIC_API_URL set), the cookie was dropped and the endpoint
      // returned 401 -> the catch below set missing=["(erreur upload)"].
      const data = await apiClient.postForm<CarteModelUploadResponse>(
        "/api/carte/upload-model-folder",
        form,
        { timeoutMs: 5 * 60_000 },
      );

      onUploadSuccess(data);

      if (data.valid) {
        toast.success(`Modele ${kind.toUpperCase()} valide et pret`);
      } else {
        toast.warning(
          `Modele ${kind.toUpperCase()} incomplet : ${data.missing_files.join(", ")}`,
        );
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Erreur inconnue";
      toast.error(`Erreur upload modele ${kind.toUpperCase()} : ${message}`);
      onUploadError();
    } finally {
      onUploadFinally();
    }
  };

  const handleClear = () => {
    onClear();
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div
      className={`space-y-3 ${
        dimWhenEmpty && !folderName ? "opacity-70" : ""
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        // webkitdirectory / directory : non-standards mais largement supportes
        // (cast via {...attrs} pour eviter le warning React unknown DOM prop).
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        multiple
        className="hidden"
        onChange={handleFiles}
      />
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs font-medium text-slate-200">{label}</span>
        {showLoadedBadge &&
          (valid === true ? (
            <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
              Charge
            </span>
          ) : (
            <span className="text-[10px] text-slate-500 bg-surface-light px-1.5 py-0.5 rounded">
              Non charge
            </span>
          ))}
      </div>
      {hint && <p className="text-[10px] text-slate-400 -mt-1.5">{hint}</p>}
      <FolderBrowseButton
        folderName={folderName}
        isUploading={isUploading}
        onClear={handleClear}
        onClick={() => inputRef.current?.click()}
        label={browseLabel}
        description={browseDescription}
      />
      {isUploading && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Loader2 size={14} className="animate-spin" />
          <span>Upload et validation...</span>
        </div>
      )}
      <ValidityBadge valid={valid} missing={missing} />
    </div>
  );
}
