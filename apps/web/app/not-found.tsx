import Link from "next/link";
import { FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="min-h-[calc(100vh-3rem)] flex items-center justify-center p-6">
      <div className="max-w-md w-full surface-elevated p-6 space-y-4 text-center">
        <div className="mx-auto w-12 h-12 rounded-md bg-accent-subtle flex items-center justify-center text-accent">
          <FileQuestion size={24} aria-hidden="true" />
        </div>
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold text-text">404</h1>
          <p className="text-sm text-text-muted">
            La page que vous cherchez n&apos;existe pas ou a ete deplacee.
          </p>
        </div>
        <Link href="/">
          <Button variant="primary" size="sm">
            Retour a l&apos;accueil
          </Button>
        </Link>
      </div>
    </div>
  );
}
