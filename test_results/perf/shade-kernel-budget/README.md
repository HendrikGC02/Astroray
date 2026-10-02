# Shade-kernel register budget (pkg300 Phase 1)

- `pareto.png` / `pareto.json`: fresh build time against Cornell-pair render speedup for each
  configuration tried. The dashed line is the 1.3x build cap; the dotted line is the 1.8x target.
- `speedup.png` / `speedup.json`: shipped build (8172ffa5) against main, min of 5 interleaved.

Producer: `benchmarks/wavefront_baseline.py --cornell-pair --env-sweep ...` (Cornell pair).
Report: `.astroray_plan/docs/pkg300-shade-counter-attribution.md`.
