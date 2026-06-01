/**
 * Hero — title + subtitle + tagline.
 * The /login page sits over the LoginNightVideoBg (top-down night
 * intersection + drift particles), so plain `text-zinc-*` colors fade
 * into the brighter passages of the video. We pair brighter text
 * colors with `login-title-shadow` / `login-text-shadow` (defined in
 * globals.css) to recover WCAG AA contrast without losing the sober
 * Linear/Vercel feel.
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
        Data Engineering
        <span className="mx-2 text-zinc-400">&middot;</span>
        Machine Learning
        <span className="mx-2 text-zinc-400">&middot;</span>
        Cartographie
        <span className="mx-2 text-zinc-400">&middot;</span>
        Full-Stack
      </p>

      <p
        data-enter="tagline"
        className="login-text-shadow text-sm text-zinc-200"
      >
        FastAPI et TensorFlow/Keras au backend, Next.js 16 et MapLibre GL JS
        au frontend. Ingestion multi-format, batchs ML iteratifs avec
        amelioration progressive du parametrage, rapports stratifies et
        visualisation neon en production.
      </p>
    </div>
  );
}
