# Random-Walk BSSRDF (subsurface scattering) — Research

**Date:** 2026-08-08. **Author:** package-implementer (bssrdf-random-walk-cpu).
**Context:** pkg178 decision **D2** defers the "full random-walk BSSRDF" path
while the Principled spine ships an approximate SSS placeholder. This note +
the CPU prototype it accompanies develop that hard random-walk subsystem in
parallel, so the two converge when the walk is ready. **CPU-only this round;
GPU is DEFERRED to the lead.**

---

## Paper(s)

The random-walk BSSRDF is an *assembly* of published pieces; each is cited
per-function in the code.

- **Setup / parameter mapping (color+radius → scattering albedo, extinction):**
  - Chiang, Kutz, Burley, *Practical and Controllable Subsurface Scattering
    for Production Path Tracing*, ACM SIGGRAPH 2016 Talks. DOI:10.1145/2897839.2927433.
    (the arctan albedo→single-scatter-albedo remap; used for `g < 0`.)
  - d'Eon, *A Hitchhiker's Guide to Multiple Scattering* (2016), Eq. (53.7) —
    the van de Hulst similarity inversion Cycles uses for `g >= 0`.
- **Guided sampling (the "hard" part the owner wants):**
  - Křivánek & d'Eon, *A Zero-variance-based Sampling Scheme for Monte Carlo
    Subsurface Scattering*, ACM SIGGRAPH 2014 Talks. (Dwivedi / zero-variance
    direction guiding.)
  - Meng, Hanika, Dachsbacher, *Improving the Dwivedi Sampling Scheme*,
    EGSR 2016 / CGF 35(4). (`sample_phase_dwivedi`, the stretched-distance
    scheme — Eq. 9/10 reproduced below.)
  - d'Eon & Křivánek, *Zero-Variance Theory for Efficient Subsurface
    Scattering*, SIGGRAPH 2020 Courses. PDF: https://eugenedeon.com/pdfs/zv2020.pdf.
    (the closed-form diffusion length, Eq. 67 reproduced below.)
- **Phase function:** Henyey & Greenstein 1941 (standard HG sampling/eval).

## Reference implementation

- **Repo:** https://github.com/blender/cycles (Blender's standalone Cycles mirror).
- **Commit / tag:** `main` as fetched 2026-08-08 (Blender 5.2-era). Pin the exact
  SHA before the GPU port lands.
- **License:** the two files carry `SPDX-License-Identifier: Apache-2.0`
  (`SPDX-FileCopyrightText: 2011-2022 Blender Foundation`). **Compatible with
  Astroray's MIT** LICENSE: Apache-2.0 permits redistribution with attribution;
  we ported the math (not a verbatim file copy) and cite per-function, mirroring
  the existing `energy_compensation.h` / `disney.cpp` Cycles-port convention.
  Recorded in `THIRD_PARTY.md`.
- **Files we mirror:**
  - `src/kernel/integrator/subsurface_random_walk.h` — the walk loop, the
    color→(alpha, sigma_t) mapping, channel MIS, the Dwivedi diffusion length,
    `eval/sample_phase_dwivedi`, `guided_fraction`.
  - `src/kernel/closure/bssrdf.h` — the `Bssrdf` closure fields (radius, albedo,
    anisotropy, ior) and `bssrdf_setup_radius` scaling per method.

## What we reproduce (CPU prototype, this round)

Equations (all in `include/astroray/bssrdf_random_walk.h`, cited inline):

1. **Extinction from radius** (`subsurface_random_walk.h`):
   `sigma_t' = 1 / max(radius, 1e-16)`, `sigma_t = sigma_t' / (1 - g)`.
2. **Single-scatter albedo from subsurface color** (van de Hulst inversion,
   `g >= 0`, d'Eon 2016 Eq. 53.7 as coded in Cycles):
   ```
   s      = 4.09712 + 4.20863*A - sqrt(9.59217 + 41.6808*A + 17.7126*A*A)
   alpha  = (1 - s*s) / (1 - g*s*s)
   ```
   (`g < 0` legacy arctan remap from Chiang 2016 recorded below but not the
   prototype default — see *Differences*.)
3. **Low-albedo throughput clamp** (Cycles): if `alpha < 0.2`,
   `throughput *= alpha/0.2; alpha = 0.2` — keeps the estimator unbiased while
   bounding walk length in nearly-absorbing media.
4. **Channel MIS (balance heuristic over RGB)** for both the collision and the
   boundary-exit events — the reason a *colored* medium stays unbiased.
5. **Classic step transport:** distance `t = -ln(1-u)/sigma_t[ch]`; on collision
   `throughput *= sigma_s*exp(-sigma_t*t) / P_collision`; on reaching the
   boundary `throughput *= exp(-sigma_t*d) / P_exit`, then exit. HG phase sampled
   exactly so its eval/pdf cancels in the classic branch.
6. **Dwivedi direction guiding** (Křivánek-d'Eon 2014, d'Eon 2020) —
   *experimental, opt-in (`useDwivedi=true`)*:
   - diffusion length (zv2020 Eq. 67):
     `v = 1 / sqrt(1 - alpha^(2.44294 - 0.0215813*alpha + 0.578637/alpha))`
   - `phase_log = log((v+1)/(v-1))`
   - eval (Meng 2016 Eq. 9): `p(mu) = 1 / ((v - mu) * phase_log)` (normalized on
     mu = cos-to-outward-normal in [-1,1]; solid-angle pdf divides by 2*pi)
   - sample (Meng 2016 Eq. 10): `mu = v - (v+1) * exp(-u * phase_log)`
   - `guided_fraction = 1 - max(0.5, |g|^0.125)` (Cycles).
   - Combined with the classic HG direction via **one-sample MIS (balance
     heuristic)** on the *direction* pdf, so the true HG phase integrand is
     importance-sampled toward the exit boundary without bias.

Data structures: a POD `Float3` (RGB / vector; layout-identical to CUDA
`float3`), `RandomWalkParams`, `RandomWalkCoefficients`, `WalkResult`. Geometry
is abstracted behind a caller-supplied `intersect(origin, dir, tmax) ->
{t, normal, hit}` functor (templated — no `std::function`, GPU-lambda friendly).

## What we deliberately do NOT take (this round)

- **Distance stretching** (Meng 2016's stretched `sigma_t' = sigma_t*(1-mu/v)`)
  — the prototype guides *direction* only. **Measured consequence (this
  round):** direction-only guiding is unbiased and low-variance for GRAY media
  (test [D] below), but for COLORED media it has pathological (near-infinite)
  variance and does NOT converge at reasonable sample counts — a colored
  furnace channel read 810 instead of ~1.0 at N=4e5. Root cause: the zero-
  variance property of Dwivedi comes from COUPLING direction guiding with
  distance stretching *per channel*; guiding direction alone with a single
  (averaged) diffusion length over-guides the high-albedo channels and the
  per-step weights compound over long low-absorption walks. The correct fix is
  the full joint per-channel scheme (stretched `sigma_t` + the direction/
  distance/channel MIS), which is DEFERRED to the GPU/follow-up stage; the
  exact Cycles formula is recorded here. **The verified prototype therefore
  ships classic channel-MIS as the default; Dwivedi is opt-in and valid for
  gray media only until the distance-stretching companion lands.** This is the
  key research finding of the round.
- **Backward guiding** toward a detected opposite surface (Cycles' bounce-0
  `opposite_distance` + `backward_fraction` logic) — an efficiency add-on for
  thin slabs, not a correctness requirement. Deferred with its formula noted.
- **RANDOM_WALK_SKIN dipole radius rescale** and the `g < 0` arctan remap
  branch — prototype targets the common `g >= 0` van de Hulst path; the skin
  path is recorded for the follow-up.
- Fresnel refraction at the entry/exit interface (Cycles enters along `-N`; the
  prototype does the same and leaves the entry/exit Fresnel + rough-dielectric
  boundary to the pkg178 closure-stack integration, where the specular lobe
  already handles it).

## Integration seam into Astroray's CPU transport (for pkg178 Stage 3)

A random-walk BSSRDF is **not** a BRDF closure — it cannot be expressed through
`Material::eval/sample` alone, because the walk needs to intersect the *scene
geometry of the object it is inside*. The seam is in the integrator, not the
material:

1. At a surface hit, if the material's closure stack contains a `Bssrdf`
   sub-closure (weight `subsurface_weight`), the integrator, when it selects
   that lobe, calls `bssrdf::randomWalk(params, P, N, sceneIntersector, rng)`.
2. `sceneIntersector` is a thin adapter over Astroray's existing
   ray/BVH intersection **restricted to the same object** (Cycles uses
   `scene_intersect_local`; Astroray's equivalent is an object-local BVH query —
   the lead wires this; for the prototype it is an analytic slab/sphere functor).
3. On `WalkResult.exited`, the integrator moves the path vertex to
   `exitPoint`/`exitNormal`, multiplies path throughput by `WalkResult.throughput`,
   and continues with a **diffuse lobe** at the exit (Cycles: `bsdf_diffuse_setup`;
   NEE + BSDF sampling proceed from the exit point). On `!exited` (throughput
   killed / max bounces) the path is terminated.
4. Spectral: the walk is RGB-channel-wise (radius/albedo are RGB — this matches
   Cycles' `Spectrum`). The exit diffuse lobe's spectral eval upsamples the
   *exit throughput as a reflectance colour* (per memory
   `spectral-upsample-nonlinearity-scaled-bsdf`), not per-λ inside the walk.
   pkg178's spectral-native discipline applies at the exit lobe, not to the walk
   coefficients.

**Interface pkg178 Stage 3 should adopt (stable):**
```cpp
namespace astroray::bssrdf {
  struct RandomWalkParams { Float3 albedo, radius; float anisotropy, ior; };
  RandomWalkCoefficients setupCoefficients(const RandomWalkParams&);
  template <class Intersector, class RNG>
  WalkResult randomWalk(const RandomWalkParams&, Float3 entryP, Float3 entryN,
                        const Intersector&, RNG&, bool useDwivedi = true);
}
```
`Intersector`: `BoundaryHit operator()(Float3 origin, Float3 dir, float tmax) const;`

## Comparison to Astroray's existing approximate SSS

- `plugins/materials/subsurface.cpp` (64 lines): a Lambertian-ish BRDF with an
  `exp(-distance/scatter_distance)` transmission tint. It does **no** volume
  walk, produces no lateral light transport / true translucency, and its
  "distance" is a per-shading-point heuristic. It is a cheap look, not a BSSRDF.
- `disney.cpp` `subsurface_`: Burley-Hanrahan-Krueger BRDF approximation
  (pkg108 BUG-16) — again a local BRDF blend, no transport.
- The random-walk prototype is the first **transport-correct** SSS: light
  actually enters, scatters through the medium, and exits elsewhere, so it
  reproduces translucent falloff and colour bleeding the approximations cannot.
  The eventual switch (pkg178 D2 → follow-up) replaces the approximate lobe's
  weight with the walk when `subsurface_method == RANDOM_WALK`.

## GPU port (DEFERRED — notes for the lead)

- The core header is POD (`Float3` ≡ `float3`) and templated on the intersector
  and RNG — no STL in the hot path, no `std::function` — precisely so a
  `__device__` twin is a mechanical port. The intersector becomes an object-local
  BVH traversal in the wavefront kernel.
- The walk is a **loop with an unbounded bounce count** (up to `BSSRDF_MAX_BOUNCES
  = 256`) that intersects geometry each bounce — this is a *new kind* of shade
  work for the wavefront scheduler (it is not a single-shot closure eval). The
  register/latency budget and whether it needs its own queue/stage is the lead's
  Stage-2/3 sizing decision (memory `wavefront-shade-kernels-register-saturated`).
- `powf`, `logf`, `expf` per bounce; the diffusion-length `powf` with a
  reciprocal exponent is the most expensive term — precompute per material.

## Parity scene for the lead (hardware)

Once wired: a subsurface slab / sphere (single scatter-radius, white albedo)
under a constant environment, rendered flag-on vs a Blender 5.2 Cycles
`subsurface_method='RANDOM_WALK'` reference via the pkg119-B differential harness
/ pkg71 cycles-parity benches. The furnace expectation (white, non-absorbing:
total exitant = incident) is checked below in CPU already; the hardware leg
checks the *spatial* falloff and colour against Cycles. Per-channel mean-ratio
gate, linear, floor+ceiling (pkg166 / memory `ssim-wrong-gate-for-independent-rng`).

## CPU prototype test results (measured, this worktree)

Standalone, g++-buildable (`g++ -std=c++17 -O2 -I include
tests/cpp/test_bssrdf_random_walk.cpp`), no CUDA / no pybind. Built & run with
MinGW g++ 15.2 in this worktree, N=4e5 walks/case, exit code 0. Measured:

- **[A] White furnace** (albedo=1, non-absorbing slab d=2 mfp): mean exit
  throughput = **1.0000** for BOTH classic and Dwivedi (energy conserved,
  linear); R+T = 1.0000; zero walks hit the bounce ceiling.
- **[B] Absorption** (classic): meanThru = 0.500 / 0.841 / 0.992 at albedo
  0.3 / 0.6 / 0.9 — monotone, all < 1 (energy absorbed).
- **[C] Translucent falloff** (classic, albedo=1): transmittance
  0.798 → 0.483 → 0.179 and reflectance 0.202 → 0.517 → 0.821 as thickness
  0.5 → 2 → 8 mfp; R+T = 1.000 throughout (conserved).
- **[D] Variance** (gray, albedo 0.95, d=8): classic stderr 2e-5, Dwivedi
  stderr 7e-5 — same mean (unbiased), but Dwivedi does **not** beat classic
  here because the classic walk is already near-zero-variance at α≈1 (its
  throughput is ~deterministic). Dwivedi's benefit is in regimes where the
  classic walk is noisy, not these furnace cases.
- **[E] Colored** (classic): per-channel meanThru = (0.993, 0.842, 0.500) —
  correct per-channel diffuse reflectances, no channel gains energy.
- **[F] FINDING** (report-only): Dwivedi on the same colored medium reads
  (10.7, 5.6, 1.3) with a per-walk max of ~8e4 — the non-convergence the
  direction-only guiding produces on colored media (see above).

## Open questions (for the lead / owner)

- Object-local BVH query: does Astroray expose an "intersect within this object
  only" path, or does the integrator need one added? (Cycles has
  `scene_intersect_local`.) This is the single biggest wiring dependency.
- Which SSS method(s) to expose: van de Hulst (`g>=0`) is prototyped;
  RANDOM_WALK_SKIN (dipole rescale) and the arctan (`g<0`) remap are follow-ups —
  confirm scope when pkg178 D2 converges.
- Distance stretching + backward guiding: land in the GPU stage, or a CPU
  follow-up first for A/B variance measurement?
</content>
</invoke>
