/**
 * Barrel for GSAP animation helpers.
 *
 * Consumers should prefer importing from this index rather than the underlying
 * module so we have a single migration point if the helpers are split further.
 */
export {
  samBounce,
  samCleanup,
  samFloat,
  samMoodEnter,
  samShake,
  samWave,
  samWorkingFocus,
  type SamAnim,
  type SamMood,
  type SamMoodHandle,
  type SamTarget,
} from "./sam-cutout";
