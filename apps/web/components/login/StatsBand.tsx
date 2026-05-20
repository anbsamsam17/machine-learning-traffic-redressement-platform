type Stat = {
  value: string;
  label: string;
  caption: string;
};

const STATS: Stat[] = [
  {
    value: "4",
    label: "modes",
    caption: "TV · PL · Carte · Compteurs",
  },
  {
    value: "95%",
    label: "précision moyenne",
    caption: "GEH < 5 sur validation",
  },
  {
    value: "12K+",
    label: "segments",
    caption: "traités par jour",
  },
];

export function StatsBand() {
  return (
    // login-glass scrim recovers the contrast lost over the animated city
    // background. The 3-column grid keeps tabular-nums alignment intact.
    <div
      data-enter="stats"
      className="login-glass grid grid-cols-3 divide-x divide-white/[0.08] rounded-lg"
      role="list"
      aria-label="Statistiques plateforme"
    >
      {STATS.map((s) => (
        <div
          key={s.label}
          role="listitem"
          className="flex flex-col gap-1 px-3 py-4 md:px-5"
        >
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-xl font-semibold tabular-nums text-white md:text-2xl">
              {s.value}
            </span>
            <span className="text-[0.7rem] uppercase tracking-wider text-zinc-300 md:text-xs">
              {s.label}
            </span>
          </div>
          <p className="text-[0.7rem] text-zinc-400 md:text-xs">{s.caption}</p>
        </div>
      ))}
    </div>
  );
}
