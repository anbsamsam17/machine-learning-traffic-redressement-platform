"use client";

import { useEffect } from "react";
import Link from "next/link";
import { AlertTriangle, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-[calc(100vh-3rem)] flex items-center justify-center p-6">
      <div className="max-w-md w-full surface-elevated p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-md bg-danger/10 flex items-center justify-center text-danger">
            <AlertTriangle size={20} aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-text">
              Une erreur est survenue
            </h2>
            <p className="text-xs text-text-muted">
              L&apos;application a rencontre un probleme inattendu.
            </p>
          </div>
        </div>
        {error.message && (
          <p className="text-xs font-mono text-text-muted bg-bg-subtle rounded p-2 break-all">
            {error.message}
          </p>
        )}
        {error.digest && process.env.NODE_ENV !== "production" && (
          <p className="text-[10px] font-mono text-text-subtle">
            digest: {error.digest}
          </p>
        )}
        <div className="flex gap-2">
          <Button onClick={reset} variant="primary" size="sm">
            <RotateCw size={14} aria-hidden="true" />
            Reessayer
          </Button>
          <Link href="/">
            <Button variant="secondary" size="sm">
              Retour a l&apos;accueil
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
