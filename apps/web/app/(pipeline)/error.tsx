"use client";

import { useEffect } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function PipelineError({
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
    <div className="surface-elevated p-6 space-y-4 max-w-md mx-auto">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-md bg-danger/10 flex items-center justify-center text-danger">
          <AlertTriangle size={20} aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-text">
            Erreur dans le pipeline
          </h2>
          <p className="text-xs text-text-muted">
            Cette etape n&apos;a pas pu se charger correctement.
          </p>
        </div>
      </div>
      {error.message && (
        <p className="text-xs font-mono text-text-muted bg-bg-subtle rounded p-2 break-all">
          {error.message}
        </p>
      )}
      <Button onClick={reset} variant="primary" size="sm" icon={<RotateCw size={14} aria-hidden="true" />}>
        Reessayer
      </Button>
    </div>
  );
}
