import { Logo } from "@/components/login/Logo";
import { HeroSection } from "@/components/login/HeroSection";
import { FeaturesPills } from "@/components/login/FeaturesPills";
import { StatsBand } from "@/components/login/StatsBand";
import { LoginForm } from "@/components/login/LoginForm";
import { LoginNightVideoBg } from "@/components/login/animations/LoginNightVideoBg";
import { SignalLights } from "@/components/login/animations/SignalLights";
import { PageEnter } from "@/components/login/animations/PageEnter";

export const metadata = {
  title: "Connexion — MDL Trafic",
  description:
    "Plateforme interne d'analyse et de redressement des données de trafic routier",
};

export default function LoginPage() {
  return (
    // Root layout already provides <main id="main-content">. Use <div> here.
    // Refonte 2026-06 : background is now the cinematic LoginNightVideoBg
    // (top-down night intersection + 24 drift particles). The previous
    // ParticleField + atmospheric blobs + NetworkGraph layers were retired
    // to avoid stacking competing motion over the new video scene.
    <div className="relative min-h-screen overflow-hidden bg-zinc-950 text-zinc-100">
      <LoginNightVideoBg />

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
              <StatsBand />
            </section>

            {/* RIGHT — 2/5 ≈ 40%, sticky-centered on desktop. */}
            <section className="flex flex-col items-center justify-center gap-6 lg:col-span-2 lg:sticky lg:top-10 lg:self-start">
              <div className="w-full max-w-md">
                <LoginForm glassVideoMode />
              </div>
            </section>
          </div>

          {/* Footer */}
          <footer
            data-enter="footer"
            className="login-text-shadow mt-12 border-t border-white/[0.1] pt-4 text-xs text-zinc-300"
          >
            © Outils a usage interne uniquement
          </footer>
        </div>
      </PageEnter>
    </div>
  );
}
