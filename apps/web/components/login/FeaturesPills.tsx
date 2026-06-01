import { Brain, Radio, Route, Activity } from "lucide-react";
import type { ComponentType, SVGProps } from "react";

type Feature = {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  title: string;
  desc: string;
  accent: string; // text- color class for icon
};

const FEATURES: Feature[] = [
  {
    icon: Brain,
    title: "Machine Learning",
    desc: "TensorFlow/Keras, grid search 11 axes, reproductibilite bit-a-bit.",
    accent: "text-indigo-300",
  },
  {
    icon: Radio,
    title: "Capteurs SIREDO",
    desc: "Boucles et permanents Siredo. Sample weights x4, stratification TMJA.",
    accent: "text-cyan-300",
  },
  {
    icon: Route,
    title: "Donnees FCD",
    desc: "Traces HERE croisees avec compteurs terrain, classes fonctionnelles FC1-FC5.",
    accent: "text-amber-300",
  },
  {
    icon: Activity,
    title: "Modelisation",
    desc: "Saturation hierarchique v3, arrondi progressif, GEH<5 sur bootstrap CI95.",
    accent: "text-emerald-300",
  },
];

function FeaturePill({ icon: Icon, title, desc, accent }: Feature) {
  return (
    // login-glass-soft: dark semi-opaque scrim + backdrop blur so the pill
    // reads cleanly over the busy animated city background. Hover lifts it
    // a touch and brightens the scrim for affordance.
    <div className="login-glass-soft group h-full rounded-lg p-4 hover:-translate-y-0.5">
      <Icon
        className={`mb-3 h-5 w-5 ${accent}`}
        aria-hidden="true"
        strokeWidth={1.75}
      />
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-zinc-300">{desc}</p>
    </div>
  );
}

export function FeaturesPills() {
  return (
    <div
      data-enter="features"
      className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4"
      role="list"
    >
      {FEATURES.map((f) => (
        <div role="listitem" key={f.title} className="h-full">
          <FeaturePill {...f} />
        </div>
      ))}
    </div>
  );
}
