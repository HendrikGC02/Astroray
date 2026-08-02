# pkg172 — diagnosis: the residual is NOT triangle-specific; it is a ~0.6%/bounce diffuse energy discrepancy, and the pkg156 ORACLE is the outlier

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
clamp (`clampDirect/Indirect` default 0 = identity), and toXYZ/CMF (shared).

## The real structure (three-way cross-check, same wall scene, albedo 0.5, env white)

| integrator | reflected luminance | vs analytic 0.5 |
|---|---|---|
| CPU `multiwavelength_path_tracer` (pkg156 oracle) | [0.5001, 0.5009, 0.4915] | ~exact |
| CPU `path_tracer` (canonical) | [0.4970, 0.4978, 0.4884] | −0.6% |
| GPU wavefront (naive) | [0.4979, 0.4988, 0.4895] | −0.4% |

- **GPU wavefront ≈ CPU `path_tracer`** (ratio 1.002) — the GPU is NOT the
  outlier; it agrees with the canonical CPU production integrator.
- **CPU `multiwavelength_path_tracer` is the outlier** — ~0.6% brighter than both,
  and it is the one that matches the energy-conserving analytic (a 0.5-albedo
  Lambertian under unit illumination must reflect exactly 0.5).

So the pkg156 gate ("GPU/CPU divergence") is really: the GPU faithfully matches
the canonical CPU path tracer, but the gate's chosen ORACLE (CPU
multiwavelength) is the ~0.6%/bounce outlier. Restoring the gate to 0.998 by
making the GPU match CPU-mw would move the GPU AWAY from the canonical
`path_tracer`. Conversely, the CPU-mw being closest to the analytic suggests
`path_tracer` + GPU share a ~0.6%/bounce diffuse ENERGY LOSS that CPU-mw does not.

## Why this is an escalation, not a fix

There is a genuine design fork the owner must decide — this is not a single
convicted line:

1. **CPU-mw is right (energy-conserving):** then `path_tracer` AND the GPU
   wavefront share a ~0.6%/bounce diffuse energy-loss bug to fix — a broad change
   touching the canonical CPU integrator and the production GPU path, far beyond a
   triangle-geometry tweak, and it would shift many existing `path_tracer` gates.
2. **`path_tracer`/GPU are right:** then the pkg156 gate's oracle is wrong and the
   gate should compare against `path_tracer`, not `multiwavelength_path_tracer` —
   a gate/oracle change, not a transport fix.
3. The 0.6% compounds over the pkg156 room's multiple bounces to the observed
   ~1.5% ([1.016,1.010,1.014]); either resolution must be measured on the full
   scene.

Per the spec ("if 0.998 is unreachable, escalate with the next-level
decomposition — the gate does not re-pin below 0.998 a second time without an
owner"), pkg172 stops here and escalates. **pkg156 stays at 0.995; no re-pin.**
Root cause of the CPU-mw vs `path_tracer` divergence (MIS/env-handling/energy
convention) is the next drill-down, owner-directed.

## pkg153 intel

No fix applied, so no movement to report. But the discriminator is now sharper:
pkg153's drift is CHROMATIC/emitter-linked; this is ACHROMATIC and present with no
emitter (env-only). Distinct mechanisms, consistent with the scope fence.
