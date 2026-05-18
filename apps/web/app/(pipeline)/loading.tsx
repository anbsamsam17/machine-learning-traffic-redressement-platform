export default function PipelineLoading() {
  return (
    <div className="space-y-4" aria-live="polite" aria-busy="true">
      <div className="skeleton h-4 w-1/4" />
      <div className="skeleton h-8 w-1/2" />
      <div className="skeleton h-32 w-full" />
      <div className="skeleton h-24 w-full" />
      <span className="sr-only">Chargement de l&apos;etape</span>
    </div>
  );
}
