"use client";

/**
 * SegmentPopupContent / SensorPopupContent — wrappers React des popups de
 * /visualisation, exposant aussi des helpers `toHtml()` pour MapLibre.
 *
 * Pourquoi un composant React + un helper string :
 *   - MapLibre setHTML() exige une string. Les builders dans
 *     lib/visualisation/popup-html.ts produisent cette string (extraits
 *     verbatim du markup original pour preservation pixel-perfect).
 *   - Si on veut un jour rendre ce contenu dans un panneau lateral React
 *     plutot que dans le popup MapLibre, on a deja la primitive React.
 *
 * Le composant React duplique structurellement le rendu HTML inline. C'est
 * voulu : on garde une seule source d'attributs/styles (les builders) pour
 * MapLibre, et le composant React produit *un equivalent JSX* lisible pour
 * un futur switch d'integration. La parite visuelle n'est pas un enjeu
 * critique tant que MapLibre reste l'unique consommateur (cas actuel).
 */

import {
  renderSegmentPopupHtml,
  renderSensorPopupHtml,
  type SegmentPopupContext,
  type SensorPopupContext,
} from "@/lib/visualisation/popup-html";

export type { SegmentPopupContext, SensorPopupContext };

/**
 * Compose la string HTML pour un popup MapLibre de segment.
 * Reexporte pour rester proche du composant lors de l'import.
 */
export function segmentPopupHtml(ctx: SegmentPopupContext): string {
  return renderSegmentPopupHtml(ctx);
}

export function sensorPopupHtml(ctx: SensorPopupContext): string {
  return renderSensorPopupHtml(ctx);
}

/**
 * Composant React equivalent : injecte le HTML brut dans une <div>. Utile
 * pour Storybook / tests / panneau lateral. Les usages MapLibre passent
 * directement par segmentPopupHtml().
 *
 * NB : on utilise dangerouslySetInnerHTML par construction (le builder
 * applique deja escapeHtml() sur les inputs user-controlled).
 */
export function SegmentPopupContent(props: SegmentPopupContext) {
  return (
    <div
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: segmentPopupHtml(props) }}
    />
  );
}

export function SensorPopupContent(props: SensorPopupContext) {
  return (
    <div
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: sensorPopupHtml(props) }}
    />
  );
}
