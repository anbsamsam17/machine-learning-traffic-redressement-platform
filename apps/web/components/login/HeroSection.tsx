/**
 * Hero — title + subtitle + tagline.
 * The /login page sits over a rich animated cityscape, so plain `text-zinc-*`
 * colors disappear into the bright background. We pair brighter text colors
 * with `login-title-shadow` / `login-text-shadow` (defined in globals.css)
 * to recover WCAG AA contrast without losing the sober Linear/Vercel feel.
 */
export function HeroSection() {
  return (
    <div className="space-y-4">
      <h1
        data-enter="title"
        className="login-title-shadow font-sans text-4xl font-bold tracking-tight text-white md:text-5xl lg:text-6xl"
      >
        Outils
        <span className="text-zinc-300"> &mdash; </span>
        <span className="text-white">Engineering Trafic</span>
      </h1>

      <p
        data-enter="subtitle"
        className="login-text-shadow text-base font-medium text-zinc-100 md:text-lg"
      >
        Machine Learning
        <span className="mx-2 text-zinc-400">&middot;</span>
        Analyse des capteurs
        <span className="mx-2 text-zinc-400">&middot;</span>
        Analyse Donn&eacute;es FCD
        <span className="mx-2 text-zinc-400">&middot;</span>
        Mod&eacute;lisation Trafic
      </p>

      <p
        data-enter="tagline"
        className="login-text-shadow text-sm text-zinc-200"
      >
        Plateforme interne d&apos;analyse et de redressement des donn&eacute;es
        de trafic routier
      </p>
    </div>
  );
}
