/**
 * Barrel des composants UI partages (UX5 foundation).
 * Reserve aux nouveaux composants premium de la refonte 2.0. Les composants
 * historiques (button, glow-card kebab-case, etc.) restent importables
 * individuellement pour ne pas casser les call sites existants.
 */

export { MagneticButton } from "./MagneticButton";
export type {
  MagneticButtonProps,
  MagneticButtonVariant,
  MagneticButtonSize,
} from "./MagneticButton";

export { GlowCard as GlowCardPremium } from "./GlowCard";
export type {
  GlowCardProps,
  GlowCardTone,
  GlowCardVariant,
} from "./GlowCard";

export { ShimmerText } from "./ShimmerText";
export type { ShimmerTextProps, ShimmerVariant } from "./ShimmerText";

export { RevealOnScroll } from "./RevealOnScroll";
export type { RevealOnScrollProps, RevealVariant } from "./RevealOnScroll";

export { NeonBorder } from "./NeonBorder";
export type { NeonBorderProps, NeonTone } from "./NeonBorder";

export { ParticleField } from "./ParticleField";
export type { ParticleFieldProps, ParticleTone } from "./ParticleField";

export { StatBadge } from "./StatBadge";
export type { StatBadgeProps, StatBadgeTone, StatBadgeSize } from "./StatBadge";

export { TabGroup } from "./TabGroup";
export type { TabGroupProps, TabItem } from "./TabGroup";
