# Prototypes

Static HTML/CSS/JS design explorations for the landing and login screens
(vanilla GSAP motion, `prefers-reduced-motion` support, layered compositing).

- `landing-traffic-bg.html` — SVG + GSAP animated traffic-city background (no video, self-contained).
- `landing-traffic-video-bg.html` — video background with an SVG/GSAP data overlay.
- `login-night-video-bg.html` — night video-background login screen.

> **Note:** the background video clips (`video/*.mp4`) are intentionally excluded
> from the repository to keep it lightweight. The video-backed prototypes will
> render with an empty background region when opened from a fresh clone;
> `landing-traffic-bg.html` runs fully standalone.
