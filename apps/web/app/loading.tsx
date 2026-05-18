export default function Loading() {
  return (
    <div
      className="min-h-[calc(100vh-3rem)] flex items-center justify-center p-6"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="max-w-md w-full space-y-3">
        <div className="skeleton h-4 w-1/3" />
        <div className="skeleton h-8 w-2/3" />
        <div className="skeleton h-32 w-full" />
        <div className="skeleton h-4 w-1/2" />
      </div>
      <span className="sr-only">Chargement</span>
    </div>
  );
}
