/**
 * Lightweight success effects: confetti CSS particles and optional "ding" sound.
 * No external libraries required.
 */

const CONFETTI_COLORS = [
  "#34d399", // emerald-400
  "#6ee7b7", // emerald-300
  "#10b981", // emerald-500
  "#6366f1", // indigo-500
  "#818cf8", // indigo-400
  "#06b6d4", // cyan-500
  "#fbbf24", // amber-400
];

/**
 * Spawn CSS-only confetti particles inside a container element.
 * Falls back to document.body if no container is provided.
 * Particles self-destruct after animation ends.
 */
export function spawnConfetti(container?: HTMLElement | null, count = 24) {
  const target = container ?? document.body;
  const rect = target.getBoundingClientRect();

  // Ensure container is positioned for absolute children
  const style = getComputedStyle(target);
  if (style.position === "static") {
    target.style.position = "relative";
  }

  const wrapper = document.createElement("div");
  wrapper.className = "confetti-container";
  target.appendChild(wrapper);

  for (let i = 0; i < count; i++) {
    const particle = document.createElement("div");
    particle.className = "confetti-particle";
    const color = CONFETTI_COLORS[Math.floor(Math.random() * CONFETTI_COLORS.length)];
    const left = Math.random() * 100;
    const delay = Math.random() * 0.6;
    const duration = 1.2 + Math.random() * 0.8;

    particle.style.backgroundColor = color;
    particle.style.left = `${left}%`;
    particle.style.top = "0";
    particle.style.animationDelay = `${delay}s`;
    particle.style.animationDuration = `${duration}s`;
    particle.style.width = `${4 + Math.random() * 4}px`;
    particle.style.height = `${4 + Math.random() * 4}px`;

    wrapper.appendChild(particle);
  }

  // Cleanup after all animations finish
  setTimeout(() => {
    wrapper.remove();
  }, 2500);
}

/**
 * Play a short success "ding" sound using the Web Audio API.
 * No audio file needed -- synthesized on the fly.
 */
export function playSuccessDing() {
  try {
    const ctx = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();

    oscillator.connect(gain);
    gain.connect(ctx.destination);

    oscillator.type = "sine";

    // Two-tone ding: C5 then E5
    const now = ctx.currentTime;
    oscillator.frequency.setValueAtTime(523.25, now);       // C5
    oscillator.frequency.setValueAtTime(659.25, now + 0.12); // E5

    gain.gain.setValueAtTime(0.15, now);
    gain.gain.exponentialRampToValueAtTime(0.01, now + 0.4);

    oscillator.start(now);
    oscillator.stop(now + 0.4);

    // Cleanup
    oscillator.onended = () => ctx.close();
  } catch {
    // Audio API not available — silently skip
  }
}
