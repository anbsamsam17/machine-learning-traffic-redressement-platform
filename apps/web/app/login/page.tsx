import { Logo } from "@/components/login/Logo";
import { HeroSection } from "@/components/login/HeroSection";
import { FeaturesPills } from "@/components/login/FeaturesPills";
import { StatsBand } from "@/components/login/StatsBand";
import { LoginForm } from "@/components/login/LoginForm";
import { LoginBg } from "@/components/login/animations/LoginBg";
import { SignalLights } from "@/components/login/animations/SignalLights";
import { NetworkGraph } from "@/components/login/animations/NetworkGraph";
import { PageEnter } from "@/components/login/animations/PageEnter";

export const metadata = {
  title: "Connexion — MDL Trafic",
  description:
    "Plateforme interne d'analyse et de redressement des données de trafic routier",
};

export default function LoginPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-zinc-950 text-zinc-100">
      {/* Animated FCD background — full-bleed, low opacity, decorative only */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-0"
      >
        <LoginBg />
      </div>

      {/* Subtle radial atmospherics — no glow on UI, just air */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
      >
        <div className="absolute -top-40 -left-40 h-[480px] w-[480px] rounded-full bg-indigo-900/[0.08] blur-3xl" />
        <div className="absolute -bottom-40 -right-40 h-[480px] w-[480px] rounded-full bg-cyan-900/[0.06] blur-3xl" />
      </div>

      <PageEnter>
        <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-7xl flex-col px-6 py-8 lg:px-10 lg:py-10">
          {/* Header */}
          <header
            data-enter="header"
            className="flex items-center justify-between"
          >
            <Logo />
            <div
              className="flex items-center"
              aria-label="Indicateur d'activité ambiant"
            >
              <SignalLights />
            </div>
          </header>

          {/* Main grid — 60/40 desktop, stack mobile */}
          <div className="mt-10 grid flex-1 grid-cols-1 gap-10 lg:mt-16 lg:grid-cols-5 lg:gap-12">
            {/* LEFT — 3/5 ≈ 60% */}
            <section className="flex flex-col gap-8 lg:col-span-3 lg:gap-10">
              <HeroSection />
              <FeaturesPills />
              <div className="relative">
                <StatsBand />
                {/* Decorative neural graph, anchored bottom-right of stats */}
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute -bottom-6 right-0 hidden opacity-60 lg:block"
                >
                  <NetworkGraph />
                </div>
              </div>
            </section>

            {/* RIGHT — 2/5 ≈ 40%, sticky-centered on desktop */}
            <section className="flex items-center justify-center lg:col-span-2 lg:sticky lg:top-10 lg:self-start">
              <div className="w-full max-w-md">
                <LoginForm />
              </div>
            </section>
          </div>

          {/* Footer */}
          <footer
            data-enter="footer"
            className="mt-12 border-t border-white/[0.04] pt-4 text-xs text-zinc-600"
          >
            © MDL · usage interne
          </footer>
        </div>
      </PageEnter>
    </main>
  );
}
