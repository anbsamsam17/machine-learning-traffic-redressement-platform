/**
 * Success effects — sober (no confetti, no glow).
 *
 * The original consumer-style confetti/ding has been removed for the
 * professional redesign. These no-op shims are kept so existing call
 * sites continue to compile during migration.
 *
 * If you genuinely want a celebration moment again, swap to a GSAP
 * scale/opacity pop on the targeted card instead — guarded by
 * `prefers-reduced-motion`.
 */

export function spawnConfetti(_container?: HTMLElement | null, _count = 0): void {
  // intentionally empty — design has moved away from consumer celebration
}

export function playSuccessDing(): void {
  // intentionally empty — design has moved away from consumer celebration
}
