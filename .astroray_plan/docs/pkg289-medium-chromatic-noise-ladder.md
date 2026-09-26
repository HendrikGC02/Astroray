# pkg289 — medium chromatic-noise ladder (#913)

2026-09-27, lane ae2. Engine: batchAD build (50883f76), CPU. Evidence:
`astra_run/batchU/ae2/` (`ladder.py`, `cycles_shaft.py`, `ladder_zm1_cpu.json`,
`astro_vs_cycles_fixture.png`, `base_cpu64.png`).

## Fixture

64x64 view of a spot light (colour 0.6/0.75/1.0, 12 kW) through a bounded
homogeneous Principled fog (grey 0.5, black absorption, density 0.08, g 0.5)
onto a dark floor; Cycles twin in Blender 5.2. Metric: per-pixel normalized
variance var/mean^2 over 12 seeds, averaged over a shaft ROI, per channel (nv).
Showcase `showcase_volumes.blend` reproduces the speckle on this build.

## Rungs

| Rung | Setting (64 spp unless noted) | nv R / G / B | Verdict |
|---|---|---|---|
| 1 | Astroray, spp 16 / 64 / 256 (gated ROI) | 2.02/1.88/3.25 → 0.53/0.50/0.88 → 0.17/0.15/0.27 | converges ~1/spp (slope ≈ -0.9); no floor |
| 1 | Cycles twin (gated ROI) | 0.0052 / 0.0050 / 0.0049 | Astroray is 100x (R,G) / 180x (B) higher |
| 1 | same, bright top-of-shaft ROI | Astroray 0.68/0.62/1.17 vs Cycles 0.0014 | ~500x |
| 1 | lit floor (no in-scatter) | Astroray 0.035/0.034/0.073 vs Cycles 0.0022 | B 2x R/G, even on a surface |
| 2 | chromatic fog (0.3/0.5/0.9) vs grey | same pattern (1.06/0.59/1.10) | not σ(λ) lane inconsistency |
| 3 | white lamp vs coloured | 0.65/0.61/1.17 | not the lamp SPD |
| 4 | NEE off | shaft vanishes (delta spot) | uninformative |
| 5 | clamp | showcase clamp is 0 | not the clamp |
| — | world fog instead of box | 0.65/0.59/1.12 | same for both medium paths |
| 6 | hero-only build | not run | 2 and 3 already rule out lanes |

Means agree with Cycles to 1 % once the fog box extends below the floor. With
the box's bottom face coplanar with the floor, Cycles darkens the floor disc to
0.53x (Astroray is unchanged by the extension, Cycles is not: a Cycles
coincident-face artifact; separate issue).

## Mechanism

1. **Luminance variance of medium direct light (dominant).** Medium NEE runs
   only at a *real* free-flight scatter vertex, and absorption terminates the
   path (pAbsorb = σ_a/σ̄ = 0.5 here). Only a few of 64 camera samples per
   shaft pixel get a lamp connection. Cycles 5.2 samples a direct-light point
   on every volume segment (equiangular+distance MIS; the material's
   DISTANCE vs MULTIPLE_IMPORTANCE setting gives identical nv, 0.00130 vs
   0.00129) and applies absorption as a weight.
2. **Blue 2x factor (secondary).** The pkg206 luminance-weighted hero-λ pdf
   under-samples blue, so the B channel has ~2x the normalized variance of R/G
   on every estimator, surfaces included. Each rare shaft contribution
   therefore carries a random chroma, which is where the green/purple speckle
   comes from.

## Decision

The spec's fix options don't apply: (a) r_u/r_l is already in place (pkg270)
and rungs 2/3 rule out lane inconsistency, (b) no chromatic interaction is
involved, (c) the clamp is off. The spec gates (slope -1 ± 0.15; G/R variance
ratio within 1.5x of Cycles: Astroray 1.33 vs Cycles 1.53) already pass on the
unfixed engine, so they can't catch this defect.

Lead decision 2026-09-27: the estimator fix is a follow-up issue
(per-segment equiangular + distance direct light, Kulla & Fajardo 2012; Cycles
`shade_volume.h`; absorption as a weight). `test_pkg289_medium_chromatic_variance.py`
keeps the convergence gate and adds the gate that catches the defect (nv
<= 4x Cycles at 64 spp), `xfail(strict=True)` until that fix lands.

## #904 / #917

- #904 gap: closed by efc9f89a (`test_issue904_caustic_walk_collapse.py`).
- #917: guide snapshots are now spectra resolved with the final lambdas.
  Zero-downstream probe behind a BK7 shell: 279/4096 spurious records before,
  0 after.
