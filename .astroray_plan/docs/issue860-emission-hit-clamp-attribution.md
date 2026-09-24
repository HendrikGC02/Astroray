# #860 attribution — emission hits clamped as indirect light

**Symptom.** geometry_zoo volume cabinet (mesh-bounded cubes) rendered 0.75–0.81 of
Cycles at `volume_bounces` 0 and 4; grid volumes matched within 2 %.

**Candidates from the issue, all excluded (main build 0dd98e18, CPU):**
1. mesh → AABB lowering: the cabinet cubes are axis-aligned boxes (exact).
   Isolated backlit Scatter / Principled cubes through the addon: 0.99–1.01 of Cycles.
2. Scatter/Absorption socket lowering: same isolated renders, 0.99–1.01.
3. Single-scatter estimator: Python-API homogeneous cube vs analytic quadrature
   (point + area lights, g 0 / 0.55, back/side lit, 0.8 m and 3.2 m lamps):
   0.97–1.03 (`astra_run/batchU/u842/ss_analytic_main.txt`).

**Bisection.** Deficit remained with only the Scatter cube + the 3.2 m backlight
(0.73) and was NON-LINEAR in lamp power (900 W → 0.73, 100 W → 0.93). Setting
`sample_clamp_indirect = 0` removed it: crop 0.99 / 0.99 / 0.99 (vb 0),
0.98 / 0.99 / 0.98 (vb 4).

**Root cause.** Cycles clamps emission found by a path with `bounce - 1`
(`kernel/film/light_passes.h`: `film_write_surface_emission`,
`film_write_volume_emission`, `film_write_background` call
`film_clamp_light(kg, &L, path.bounce - 1)`; Apache-2.0). A lamp reached by the
continuation from the first vertex is DIRECT light. Astroray passed the loop
`bounce`, so that MIS leg was clamped by `sample_clamp_indirect` (Blender default
10). Bright close lamps + forward-scattering media (large phase-leg MIS weight) hit
it hardest; it also dims glossy reflections of bright lamps. pkg144's note listed
the call sites but missed the `- 1`.

**Fix.** Emission-hit clamp sites pass `bounce - 1` (CPU `pathTraceSpectral`:
lamp hit, emissive surface, background, bounded-medium emission; GPU wavefront:
the same five sites). NEE sites keep the vertex bounce. Not changed: GR emission
(no Cycles counterpart) and the legacy `pathTraceSpectralCaustic` integrator.

**Five-seed gate (CPU addon at b3873898, seeds 278, 2781–2784, crop means / Cycles).**
`volume_bounces` 0, Blender defaults (`sample_clamp_indirect` 10): 0.989 / 0.989 / 0.986.
`volume_bounces` 4 is gated with `sample_clamp_indirect = 0` in BOTH engines:
0.991 / 0.990 / 0.994. Reason (lead decision 2026-09-25): the clamp is a biased
cutoff, so the energy it removes depends on the per-sample contribution spread,
not only on the mean. #860's observable is volume transport. With the default
clamp at bounces 4, Cycles loses 2 % of the crop and Astroray 9–10 %
(scatter cube: 5 % vs 21 %; Principled: 0 % vs 3–7.5 %, blue-heavy) → 0.92 / 0.92 /
0.91. That clamp-on gap is filed separately (per-sample spread in
multi-scatter media; candidates: hero-wavelength spectral spikes, XYZ-Y vs
Cycles RGB-sum clamp metric).

**Residual (recorded, not hidden).** Backdrop seen through the saturated red
Absorption cube: 0.90 / 0.77 / 0.79 (G/B absolute ≈ 0.02) — spectral transport of
σ_a = D(1 − Color) with Color = (0.85, 0.25, 0.20) at optical depth ≈ 2 vs Cycles
RGB; unchanged by the clamp.
