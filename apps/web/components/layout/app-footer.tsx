/**
 * AppFooter — bande discrète présente en bas de chaque page.
 *
 * Choix de design :
 * - bg-slate-950/40 + backdrop-blur-sm pour rester lisible par dessus
 *   tout fond animé (cityscape de /login notamment) sans masquer le contenu.
 * - border-t slate-800 subtile pour marquer la séparation visuelle.
 * - text-xs slate-400 pour rester discret tout en restant lisible (>= 4.5:1
 *   sur les fonds sombres ciblés).
 * - mt-auto + flex parent (cf. body dans layout.tsx) pour coller en bas
 *   même sur les pages courtes, sans recouvrir le contenu sur les pages
 *   longues (pas de position fixed).
 */
export function AppFooter() {
  return (
    <footer
      className="mt-auto w-full border-t border-slate-800 bg-slate-950/40 py-4 backdrop-blur-sm"
      role="contentinfo"
    >
      <p className="text-center text-xs text-slate-400">
        Outil développé par Samir Anbri
      </p>
    </footer>
  );
}
