/**
 * MDL Trafic logo — inline SVG (road + neural node motif).
 * Sober, single-color stroke. No glow.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <div
      className={`flex items-center gap-2.5 ${className ?? ""}`}
      aria-label="MDL Trafic — logo"
    >
      <svg
        width="28"
        height="28"
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-hidden="true"
        className="text-zinc-100"
      >
        {/* Road */}
        <path
          d="M6 26 L16 6 L26 26"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.9"
        />
        {/* Dashed centerline */}
        <path
          d="M16 10 L16 24"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeDasharray="2 3"
          opacity="0.5"
        />
        {/* Neural nodes */}
        <circle cx="16" cy="6" r="2" fill="currentColor" />
        <circle cx="6" cy="26" r="1.6" fill="currentColor" opacity="0.7" />
        <circle cx="26" cy="26" r="1.6" fill="currentColor" opacity="0.7" />
        {/* Cross edges */}
        <path
          d="M6 26 L26 26"
          stroke="currentColor"
          strokeWidth="0.8"
          strokeLinecap="round"
          opacity="0.35"
        />
      </svg>
    </div>
  );
}
