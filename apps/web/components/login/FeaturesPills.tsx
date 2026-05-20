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
    desc: "Réseaux de neurones TV & PL",
    accent: "text-indigo-400",
  },
  {
    icon: Radio,
    title: "Analyse capteurs",
    desc: "Boucles électromagnétiques & vidéo",
    accent: "text-cyan-400",
  },
  {
    icon: Route,
    title: "Données FCD",
    desc: "Floating Car Data temps réel",
    accent: "text-amber-400",
  },
  {
    icon: Activity,
    title: "Modélisation",
    desc: "Redressement & évaluation",
    accent: "text-emerald-400",
  },
];

function FeaturePill({ icon: Icon, title, desc, accent }: Feature) {
  return (
    <div
      className="group rounded-lg border border-white/[0.08] bg-white/[0.02] p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-white/[0.14] hover:bg-white/[0.04]"
    >
      <Icon
        className={`mb-3 h-5 w-5 ${accent}`}
        aria-hidden="true"
        strokeWidth={1.75}
      />
      <h3 className="text-sm font-semibold text-zinc-100">{title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-zinc-500">{desc}</p>
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
        <div role="listitem" key={f.title}>
          <FeaturePill {...f} />
        </div>
      ))}
    </div>
  );
}
