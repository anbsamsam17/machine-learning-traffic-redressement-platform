/**
 * Hero — title + subtitle + tagline.
 * Strict sober: no glow, tracking-tight, muted hierarchy.
 */
export function HeroSection() {
  return (
    <div className="space-y-4">
      <h1
        data-enter="title"
        className="font-sans text-4xl font-bold tracking-tight text-zinc-50 md:text-5xl lg:text-6xl"
      >
        Outils
        <span className="text-zinc-500"> &mdash; </span>
        <span className="text-zinc-100">Engineering Trafic</span>
      </h1>

      <p
        data-enter="subtitle"
        className="text-base text-zinc-400 md:text-lg"
      >
        Machine Learning
        <span className="mx-2 text-zinc-600">&middot;</span>
        Analyse des capteurs
        <span className="mx-2 text-zinc-600">&middot;</span>
        Analyse Donn&eacute;es FCD
        <span className="mx-2 text-zinc-600">&middot;</span>
        Mod&eacute;lisation Trafic
      </p>

      <p
        data-enter="tagline"
        className="text-sm text-zinc-500"
      >
        Plateforme interne d&apos;analyse et de redressement des donn&eacute;es
        de trafic routier
      </p>
    </div>
  );
}
