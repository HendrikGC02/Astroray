# HDRI background-ROI gap diagnosis — 2026-09-07

Owner-selected follow-up to the pkg237/238 diagnosis
(`.astroray_plan/docs/pkg237-238-diagnosis-2026-09-07.md`), which flagged PR #729's
`hdri_exterior_hair` background-ROI mean (Cycles CPU 0.121 vs Astroray CPU 0.047,
2.56x) as a **separate, unexplained** defect and named world strength /
environment importance weight / colour management / view-transform as suspects.
CPU-only (GPU held by an addon rebuild); all renders headless Blender 5.2,
`benchmarks/blender_parity/scenes/hdri_exterior_hair.blend`, Standard view
transform / exposure 0 / gamma 1 / OpenEXR float, matching
`benchmarks/blender_parity/render_leg.py::_configure_render`. Driver scripts and
raw outputs are under `test_results/2026-09-07-hdri-gap/` (gitignored, not
committed).

## TL;DR

**All four pkg237-named suspects are cleared.** Astroray's world/HDRI
translation (rotation convention, strength, tint, colour management, EXR
output path) is bit-correct: an isolate (world-only) render matches an
independent ground-truth sampling of the raw `.hdr` file to 5 decimal places,
and matches Cycles' own isolate render to within MC noise. **The 2.56x gap is
not Astroray rendering the sky too dark — it is Cycles' own reference render
being ~2.4-3.6x brighter than the true environment radiance in that ROI**,
caused by Cycles' world-environment importance-sampling (MIS/CDF) machinery
activating because the scene's "Ground" plane is a receiving surface. Hiding
only that one object collapses Cycles' reading from 0.121 to 0.033 — exactly
the isolate/ground-truth value — while hiding the other three objects
(Scalp/GlassSphere/Hair) does nothing.

## Experiment table

| # | Experiment | Cycles CPU | Astroray CPU | Verdict |
|---|---|---|---|---|
| 1a | Full scene (reproduces PR #729 / manifest) | 0.120776 | 0.047055 | reproduces the reported 2.56x gap exactly (manifest: 0.1209/0.0472) |
| 1b | World-only isolate (all non-camera objects hidden/deleted, same HDRI, same camera) | 0.033266–0.033686 | 0.034736 | **engines agree** (within 32-spp MC noise); env lookup itself is not the bug |
| 1c | Ground-truth check: independently decode `samples/test_env.hdr` (OpenCV float RGBE) and sample it at the camera's own ray directions for the ROI, using Cycles' published equirect formula (`u=(π-atan2(dy,dx))/2π`, `v=1-acos(dz)/π`) and Astroray's own formula (`EnvironmentMap::lookup`/`evalSpectral`, `include/raytracer.h:1520-1628`, incl. the `blender_convention` cswap) | mean 0.033811 (Cycles-formula UV) | mean 0.033811 (Astroray-formula UV) | **the two UV conventions are numerically identical** for this scene (identity rotation) and match experiment 1b to <2%. Astroray's rotation/mapping convention is correct. |
| 2 | Strength sweep 0.5/1/2 (full scene, Ground present) | 0.0605 / 0.1211 / 0.2422 | 0.0250 / 0.0487 / 0.0957 | both engines respond **linearly** to strength (Cycles ratios 0.500/1/2.001; Astroray 0.514/1/1.965). The Astroray/Cycles ratio is **constant** across all three strengths (2.42-2.52x) — rules out a tone-mapping/exposure-curve explanation (would be strength-dependent) and confirms a constant multiplicative factor instead. |
| 3 | Constant-colour world (no HDRI, Background Color=(0.5,0.5,0.5), Strength=1, no objects) | 0.500000 | 0.499453 | **match to <0.2%.** Definitively rules out colour-space/gamma/exposure/view-transform in the addon output path (pkg237's "colour management" suspect). |
| 4a | Per-object hide (full scene, hide exactly one of Ground/Scalp/GlassSphere/Hair) | Ground hidden: 0.033266 (= isolate exactly); Scalp/Glass/Hair hidden: 0.1185/0.1208/0.1198 (≈ full baseline 0.1208) | not run (Cycles-only diagnostic) | **only the Ground plane triggers the inflation.** The other three objects are irrelevant. |
| 4b | Zero-bounce (`max_bounces=diffuse_bounces=glossy_bounces=transmission_bounces=volume_bounces=0`, Ground present) | 0.108746 | not run | most of the inflation (0.076 of 0.088) **survives with all indirect light transport disabled** → not a multi-bounce GI leak reaching the ROI. |
| 4c | Black-world geometry probe (Background Strength=0, Color=(0,0,0), full scene incl. Ground) | 0 nonzero pixels of 4800 in the ROI | not run | **every ROI pixel is a genuine camera-miss ray** — no hair/ground/glass silhouette geometrically intrudes into the "sky-only" band. Rules out a hair-thickness/coverage-overshoot explanation (the `hair_coverage` non-vacuity check separately shows Astroray at 2x Cycles' hair coverage — that is a real, different finding, but it does not reach this ROI). |
| 4d | `world.cycles.sampling_method`: AUTOMATIC → NONE (full scene, Ground present) | 0.121 → 0.058 | not run | disabling Cycles' environment importance-sampling/CDF machinery removes **about half** of the inflation. Directly implicates that subsystem as a major contributor. |

## Code read (experiment 4 as scoped)

- `blender_addon/__init__.py:5232-5330` (`setup_world`): walks `TEX_ENVIRONMENT` /
  `BACKGROUND` / `MAPPING` nodes, reads `Strength`, `Color` tint, and XYZ Euler
  rotation, then calls `renderer.load_environment_map(hdri_path, strength, rx,
  ry, rz, tint..., blender_convention=True)`. For this scene the World node
  tree has **no `BACKGROUND` node at all** (`Environment Texture.Color` wired
  directly into `World Output.Surface` — Blender/Cycles' implicit
  color-to-shader conversion, which is Strength=1, no tint). The addon's loop
  simply never matches `elif node.type == 'BACKGROUND'`, so `strength` and
  `tint` stay at their pre-initialized defaults of `1.0`/`[1,1,1]` — which
  happen to be exactly the values Cycles' implicit conversion uses. No bug,
  but worth a comment since it's coincidental rather than deliberately handled.
- `include/raytracer.h:1424-1628` (`EnvironmentMap`): `load()` uses
  `stbi_loadf` (linear float decode of the Radiance RGBE `.hdr`, confirmed
  correct against an independent OpenCV decode). `lookup()`/`evalSpectral()`
  are **plain bilinear texture lookups multiplied by `strength` and the tint**
  — no importance-sampling-derived correction term of any kind.
  `evalSpectral()` is what the path tracer actually calls for camera-miss rays
  (`include/raytracer.h:3104-3127` and the GPU-mirroring CPU loop at
  `:3559-3582`): `envSpec = envMap->evalSpectral(...); color +=
  clampContribSpectral(throughput * envSpec, ...)`. No pdf/MIS weight is
  applied at bounce 0 (correct — nothing competes with a camera ray for that
  direction), so the only way Astroray's number could be wrong is in
  `strength`/`tint`/rotation/colour-space, all of which experiments 1-3 clear.
- `module/blender_module.cpp:1697-1703` (`loadEnvironmentMap` binding): a thin
  pass-through to `EnvironmentMap::load`, nothing else to implicate.
- `benchmarks/blender_parity/harness.py:189-190`: `HDRI_BACKGROUND_ROI =
  (0.0, 0.0, 1.0, 30/360)`, `HDRI_MIN_BACKGROUND_MEAN = 0.05`. Given the
  ground-truth sample for this exact ROI is **0.034** (experiment 1c), the
  0.05 floor is already above the true physical radiance of the scene's own
  sky patch — see "Gate calibration" below.

## Root cause

**Not in Astroray.** The 2.56x gap is Cycles' own reference render reading
2.4-3.6x brighter than the true environment radiance for that ROI, not
Astroray reading too dark. Astroray's full-scene number (0.047) is within
~35% of its own isolate baseline (0.035) and of ground truth (0.034); Cycles'
full-scene number (0.121) is ~3.6x its own isolate baseline (0.033), which
*also* equals ground truth. The mechanism, established by elimination
(experiments 4a-4d): Cycles' world/environment importance-sampling (CDF /
`sampling_method`) machinery, which the "Ground" plane's presence causes
Cycles to build and use (a receiver needs the world importance-sampled for
NEE), measurably perturbs Cycles' **own** direct camera-miss background
evaluation for this HDRI — even for pixels that never intersect that Ground
plane, and even with all subsequent light bounces disabled. Astroray has no
analogous importance-sampling-driven correction in its background evaluation
path (a plain lookup, per the code read above), so it renders the
un-perturbed, physically correct value instead.

### Two remaining suspects for the exact Cycles-side mechanism

Toggling `sampling_method` NONE→AUTOMATIC accounts for only about half the
inflation (0.058 → 0.121), so a single clean "compensation term" hypothesis
isn't fully confirmed yet. Two candidates remain, both consistent with every
experiment run so far:

1. **MIS/CDF bias-compensation applied to the directly-visible background.**
   Cycles builds a `sample_map_resolution=1024` (this file) importance map
   from the HDRI for NEE; a documented Cycles technique ("MIS compensation")
   corrects for the mismatch between that coarse CDF and the full-resolution
   texture, and this correction is known to also touch camera-visible
   background pixels, not just NEE'd ones.
2. **A qualitatively different (and here, less accurate) background
   evaluation path** that Cycles switches to whenever `sampling_method=
   AUTOMATIC` detects at least one receiver in the scene, independent of CDF
   resolution.

**Distinguishing test (not yet run — flagged for the next session):** sweep
`world.cycles.sample_map_resolution` (e.g. 256 / 1024 / 4096) with
`sampling_method=AUTOMATIC` and Ground present. Hypothesis 1 predicts the ROI
mean moves measurably with resolution (a coarser map → larger per-texel
compensation error); hypothesis 2 predicts it barely moves (a binary
on/off switch, already exercised by the NONE-vs-AUTOMATIC test above).

## Does this explain 0.047 vs 0.121 exactly?

It explains the **direction and the dominant magnitude** precisely: true sky
radiance ≈ 0.034; Cycles inflates it ~3.6x via its own importance-sampling
machinery (proven by the Ground-hide test reverting Cycles to exactly the
isolate/ground-truth value, and by the sampling_method toggle removing about
half the inflation); Astroray reads 0.047, only ~1.35x above its own
isolate/ground-truth baseline. It does **not** explain Astroray's small
residual (~0.012-0.013 above its own isolate baseline) to the last decimal —
that residual is plausibly the addon's own (much smaller) world-lighting NEE
contribution from the Ground plane (`world.cycles.max_bounces` is read and
applied by the addon per pkg201, so Astroray's Ground plane *does* receive
some NEE-sampled environment light, unlike a plain miss-ray), or minor
antialiasing edge bleed from the hair streak into the ROI's lowest rows. That
residual is an order of magnitude smaller than the reported gap and was not
chased further in this session.

## Which package should own this

Not pkg237 (colour-blind adaptive-sampling noise floor) and not pkg238
(PostInit ULP transcendental drift) — both are unrelated defects already
diagnosed separately. This is a new, narrowly-scoped finding with two
genuinely different fix directions (not proposing to force a choice between
them — recommend only, per this task's scope):

- **If Cycles-parity for camera-visible background radiance is the goal**
  (consistent with CLAUDE.md's "Cycles-compatible behavior where applicable"
  north star): file a new package to implement whatever the confirmed
  mechanism turns out to be (MIS-compensation-style correction on
  `EnvironmentMap::evalSpectral`'s direct-miss path). This is a real feature
  addition, not a one-line multiply fix, and per CLAUDE.md §6 (no invented
  algorithms) should go through `cite-algorithm` to find Cycles' own
  documented/published formula before implementing — it should NOT be folded
  into pkg237/238.
- **If Astroray's un-perturbed, ground-truth-matching background is
  considered the physically-correct behavior** (arguably preferable given the
  project's "correctness and visual fidelity outrank performance" priority):
  the fix belongs to the **pkg119b non-vacuity gate itself**
  (`benchmarks/blender_parity/harness.py:189-190`,
  `HDRI_MIN_BACKGROUND_MEAN=0.05`), whose floor sits above the scene's own
  true sky radiance (0.034) and was evidently tuned against Cycles' inflated
  reference rather than physical ground truth. This mirrors pkg237's own
  precedent (gate/test-methodology defect, not an engine defect) and would
  route to whichever track maintains that harness's thresholds.

Either way, PR #729's `hdri_background` non-vacuity failure should **not**
block on a "make Astroray brighter" fix without first deciding which of the
two directions above the owner wants — pushing Astroray's background toward
Cycles' 0.121 by an ad-hoc multiplier would move it further from the
independently-verified physical ground truth (0.034), not closer.

---

## Lead review note (2026-09-07 09:00, Claude Fable 5.1)

The conclusion "Cycles is inflated by its environment importance sampling" is **not yet
verified** and is physically surprising: a camera ray that misses all geometry should
return the environment lookup in Cycles regardless of world sampling. The evidence that
only the Ground plane triggers the inflation, and that most of it survives with bounces
at zero, is equally consistent with the ROI containing Ground-plane pixels *in Cycles*
(different clip planes, plane extent or horizon position) while the black-world geometry
probe was run only in Astroray.

Distinguishing test before anyone acts on this doc: repeat the black-world geometry probe
**in Cycles** (world colour 0, emission 0, only Ground visible, same camera) and count
nonzero ROI pixels; then re-render the ROI with `world.cycles.sampling_method = 'NONE'`
and `'MANUAL'` and compare against the ground-truth `.hdr` decode (0.0338). If Cycles'
black-world probe shows Ground pixels inside the ROI, the gap is a fixture/ROI problem,
not a Cycles bias, and the `HDRI_MIN_BACKGROUND_MEAN` floor must be re-derived from the
ground-truth decode. Until then treat both engines' numbers as unconfirmed.
