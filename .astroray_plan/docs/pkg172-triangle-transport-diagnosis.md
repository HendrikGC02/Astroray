# pkg172 — diagnosis: the residual is NOT triangle-specific; it decomposes into (A) a universal ~0.6%/bounce diffuse epsilon energy-loss + (B) a separate GPU-only ~0.4% loss that owns pkg156

**Date:** 2026-08-02 (RTX 5070 Ti). **Branch:** pkg172-triangle-transport-bias
(base 80d4ec0, #541 not merged — findings below use NEUTRAL albedo, which is
#541-independent per pkg168 Step 2). **No fix applied — escalating.**

## The spec's premise is falsified, and all three named candidates are cleared

**(1) NOT triangle-specific.** With a clean full-frame single-bounce measurement
(camera face-on, uniform white env, spp 16384), a **sphere and a triangle wall
give the IDENTICAL ratio** 0.99570 (per-channel, neutral albedo 0.5). My pkg168
Step-2 "sphere-clean / triangle-dirty" reading was a camera/depth/masking
confound (the sphere and floor probes used different camera heights and path
depths). The bias is geometry-INDEPENDENT.

**(2) Candidate (c) epsilon — CLEARED.** Scratch rebuild with the throughput
epsilon `f/(pdf+1e-3)` → `1e-6` on BOTH legs left the ratio unchanged (0.99587 →
0.99590). Not the epsilon.

**(3) Candidates (a)/(b) normal/cosθ — CLEARED.** The bias is achromatic,
depth-independent (constant 0.99587 across depth 2–8 on a flat wall — no
multi-bounce, no off-by-one), and identical for sphere vs triangle. Both legs use
the normalized face normal + matching `frontFace`; a mis-normalized or non-ONB
frame cancels in `f/pdf` anyway.

Also ruled out by inspection/measurement: the JH upsampling tables (Step 1,
neutral matches to 1.000000), the diffuse closure weight (=1.0), the GPU contrib
clamp (`clampDirect/Indirect` default 0 = identity). (toXYZ/CMF NOT yet cleared —
now a prime suspect for effect (B); see below.)

## CORRECTION (clean rebuild) — the table below the line was contaminated

My first cross-check ran against a stale `.pyd`: after the epsilon probe I
reverted the SOURCE but did not rebuild, so the run used a build where the epsilon
was zeroed in `multiwavelength_path_tracer` (line 238) + GPU `stage_advance` (685)
but NOT in `path_tracer` (`raytracer.h:2549`). That falsely made CPU-mw read
0.500 "analytic-exact." RETRACTED. Corrected numbers (clean build, epsilon 1e-3
everywhere):

| integrator | reflected luminance | vs analytic 0.5 |
|---|---|---|
| CPU `multiwavelength_path_tracer` | [0.49699, 0.49777, 0.48845] | −0.6% |
| CPU `path_tracer` | [0.49699, 0.49777, 0.48845] | −0.6% (BIT-IDENTICAL to mw) |
| GPU wavefront (naive) | [0.49486, 0.49572, 0.48652] | −1.0% |

## The real structure: TWO separate effects

**(A) Universal ~0.6%/bounce diffuse energy loss — the `f/(pdf+1e-3)` epsilon.**
All three legs undershoot the analytic 0.5 by ~0.6% (CPU-mw == CPU-pt
bit-identical). An additive `1e-3` epsilon on a cosine-sampled diffuse pdf loses
exactly `2π·eps ≈ 0.628%` (E[1/cosθ]=2 over the cosine-weighted hemisphere),
matching to the digit; rebuilding at `1e-6` restores 0.500. **The pkg156 oracle
(CPU-mw) is NOT exempt — my earlier claim is RETRACTED.** This confirms the
architect's BRANCH-1 that a real ~0.6%/bounce loss exists; it is universal.
Fixing it brightens ALL diffuse ~0.6%/bounce → the large coordinated re-pin.

**(B) A separate GPU-only extra ~0.4% loss.** The GPU (0.495) sits below the
bit-identical CPU legs (0.497) even with the GPU `stage_advance` epsilon set to
`1e-6` — a DISTINCT second GPU site, upstream of the throughput update. Because
(A) cancels in the GPU/CPU ratio, **(B) — not (A) — is what the pkg156 gate ratio
(0.9957) measures.** Fixing (A) alone does NOT restore pkg156; pkg156 needs (B).

Cleared for (B): the cosine samplers are byte-identical (CPU
`Vec3::randomCosineDirection` == GPU `gpu_randomCosineDir`); GPU `f/pdf = albedo`
exactly for the single diffuse closure lobe; CMF/toXYZ share the SAME
`data/spectra/cie_cmf.inc` and MC formula; D65 norm matches (direct-bg render is
clean); the contrib clamp is default-off (identity). Every component provably
matches, yet the GPU is a stable ~0.4% low on one diffuse bounce.

**New clue — (B) is ALBEDO-DEPENDENT** (single bounce, white env, GPU/CPU ratio):

| albedo | GPU/CPU | abs deficit |
|---|---|---|
| 0.5 | 0.99589 | 0.00213 |
| 0.8 | 0.99700 | 0.00252 |

A pure throughput epsilon would give an albedo-INDEPENDENT fractional loss, so (B)
is NOT a scalar epsilon — it is a spectral-shape / spectral-product / toXYZ-
interaction effect that depends on the upsampled albedo spectrum's shape. Since
every static component matches, convicting (B) to a line now requires per-hit GPU
instrumentation ([pkg172-diag] kernel printf of throughput, envSpec, and the
per-λ contribution + XYZ for one pixel/sample, diffed against the same on CPU) —
a focused instrumented build, recommended as the next step. (B) owns pkg156.

## Status

- **(A) convicted** (epsilon; `2π·eps` math + `1e-6` probe → 0.500). Fix =
  guarded pdf at the sample site (pbrt-v4: reject when `pdf==0`, divide by the
  true pdf; never an additive bias). Broad re-pin sweep + architect sign-off
  before push.
- **(B) located** as a distinct GPU-only site, not yet convicted to a line; owns
  the pkg156 restoration.
- **pkg156 stays at 0.995; no re-pin** until (B) is fixed and measured full-scene.
- Shared −1.7% B-channel deficit vs analytic across all three legs: separate
  sensor/illuminant-normalization question, flagged for a future filing.

## pkg153 intel

No fix applied, so no movement to report. But the discriminator is now sharper:
pkg153's drift is CHROMATIC/emitter-linked; this is ACHROMATIC and present with no
emitter (env-only). Distinct mechanisms, consistent with the scope fence.
