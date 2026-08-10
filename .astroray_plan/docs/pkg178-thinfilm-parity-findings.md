# pkg178 Stage-4 — Thin-Film Saturation Parity vs Blender 5.2 Cycles

**Date:** 2026-08-11
**Oracle:** Blender 5.2 LTS Cycles (CPU, seed 7), pkg178-D1 parity oracle.
**Astroray leg:** native `"principled"` plugin, GPU (thin-film GPU path #579),
via the real addon Principled→native translation (incl. #581 thin-film sockets).
**Harness:** `benchmarks/cycles-parity/thin_film/` (identical-scene A/B, both legs
render the *same* translated Blender scene — the metal_ab pattern). Grid: thickness
{100,200,400,600,800,1000} nm × film-IOR {1.2,1.5,1.8} × kind {dielectric,conductor},
res 128, 256 spp. Report: `test_results/pkg178_thinfilm_ab/`.

## Verdict — acceptance GREEN

Per-channel Astroray/Cycles linear mean-ratio band **[0.85, 1.15]** (both bounds
asserted; pkg166). ROI = whole frame (the 0.9-radius sphere at dist 1.35 / 60° fov
overfills the frame — the whole frame is sphere, verified via corner pixels).

| kind | in-band | max |ratio−1| | hue Δ (chroma-meaningful cells) | max dE2000 |
|------|---------|-----------|--------------------------------|------------|
| **dielectric** (analytically-exact Fresnel) | **18/18** | 8.96 % | mean **6.0°**, max 13.4° (10/18 cells) | 2.42 |
| **conductor** (RGB-upsample approx) | **18/18** | **2.09 %** | mean **10.1°**, max 25.4° (8/18 cells) | 1.39 |

Visually confirmed (montage `thinfilm_astroray_vs_cycles_montage.png`): smooth
center-to-rim iridescence gradients (film path length varies with incidence angle)
matching Cycles on every pair — not salt-and-pepper noise.

## Key findings

1. **Dielectric matches Cycles** — confirming the "Belcour-Barla utility is
   analytically exact" claim. 18/18 in-band; on the cells that carry visible
   chroma, the iridescence hue tracks Cycles to **6° mean**. The scene is
   near-zero-variance (smooth surface reflecting a uniform world), so results are
   converged even at low spp (Astroray 256↔1024 spp maxabsdiff 9e-8).

2. **film-IOR = 1.5 ⇒ no iridescence (both engines).** With base dielectric IOR
   1.5, a film IOR of 1.5 removes the film/base index contrast, so there is no
   interference and the result is thickness-independent (Cycles ROI hue = NaN =
   pure grey). Astroray agrees in magnitude (ratio 0.99/0.99/0.97) with only a
   faint residual tint (dE 0.42). These 6 cells are correctly excluded from the
   "chroma-meaningful" hue statistics.

3. **Conductor gap is small** — smaller than STATUS 2026-08-11 assumed. The
   RGB-upsample conductor thin-film reproduces Cycles' *per-wavelength* film with
   per-channel RGB chroma exact to **2.09 %** and hue tracking to **10° mean /
   25° max** on saturated cells, all at **dE ≤ 1.39**. The apparent large
   circular-mean-hue deltas (raw max 127°) are entirely on near-neutral
   low-film-IOR / washed-out cells where the sphere shows no visible colour and
   the circular-mean hue is noise — perceptually there is nothing to match.

4. **per-λ-conductor follow-up → LOW priority.** The maximum refinement a spectral
   conductor film could buy is ~10–25° of hue on strongly-saturated
   metal-iridescence cells, at dE < 1.4. Not a visible parity gap at these
   configs; deprioritise relative to core work.

## Metric calibration note (for future runs)

The initial ROI was a central 44 % box (inherited from metal_ab, where the sphere
is bright). For the **dim near-black dielectric** that box lands on the sphere's
near-normal-incidence cap — the darkest region — making the red-channel ratio a
tiny-denominator artifact (one spurious FAIL at d400/film-IOR1.2, box R-ratio 0.59
vs whole-frame 0.959). Fixed by using the whole frame (the sphere overfills it).
Reproduced deterministically at 4× spp before the fix — it was an ROI artifact,
not MC noise and not an engine divergence.

## Scope

Dielectric here is a **reflective** near-black dielectric (metallic 0, transmission
0, IOR 1.5) — this isolates the thin-film *Fresnel* term, the quantity the
"analytically exact" claim is about. A fully transmissive soap bubble adds
refractive multi-bounce transport that would diverge for RNG/thin-wall reasons
unrelated to the Fresnel utility; that is a separate transport test, out of scope
for this Fresnel-parity gate.
