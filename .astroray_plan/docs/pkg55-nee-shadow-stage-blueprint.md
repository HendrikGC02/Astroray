# pkg55-B' shadow-stage blueprint — sampleDirectSpectralMW factoring

Date: 2026-06-11. Source: line-precise read of src/gpu/multiwavelength_kernel.cu
(sampleDirectSpectralMW, lines 469-578 at main 7489763) by an Explore agent +
lead refinement. Target: relieve the wavefront shade kernel's 254 regs/thread
(n7p5 profile: stage_shade_bucketed 18.8 of 34.4 ms kernel time on the
contact sheet) to close the Phase-B >=1.5x gate (currently 1.39x).

## Decision: THREE-way factoring (A/B/C), not two

- **A `gpu_nee_sample`** (sampling ONLY, no material evals): early-outs
  (isDelta/no-lights, L486-487), light selection (tree L496-502 draw#1 /
  power-CDF L503-506 draw#2), light validation (L508-512), sphere point
  sampling (L520-535, draws #3-4) or triangle point sampling (L542-557,
  draws #5-6; lightFront=true HARDCODED for triangles - asymmetry is
  original behavior), lightPdf check (L564). Returns POD: shadow ray
  (origin/wi/maxDist), lightPdf, lightMatId, isSphere, valid.
  ALL 6 RNG draws live here, in original order.
- **B `gpu_nee_occlude`** (trace ONLY): gpu_tlas_hit shadow ray with
  GRay(rec.point, wi, time) + motionVerts (pkg88). Sphere: miss-or-wrong-
  material => occluded; on pass returns sh.frontFace (L536-541). Triangle:
  any hit => occluded (L558-561). Returns {occluded, shadowFrontFace}.
- **C `gpu_nee_resolve`** (material evals + contribution): f_spec eval
  (L568-569), L_spec emission with lightFront = isSphere ? occ.frontFace :
  true (L570-572), bsdfPdf (L574), MIS power heuristic (L575), contribution
  f*L*(wt/(lightPdf+0.001)) (L577).

**Why A/B/C and not the two-way split:** the ORIGINAL evaluates f/L/pdf
AFTER the trace (lazy ordering - occluded rays skip the evals). Recomposing
the megakernel as A->B->C in that order is byte-identical INCLUDING the
lazy ordering and pays zero extra work. The wavefront runs A in the shade
stage (now traversal-free) and B->C in a dedicated shadow stage.

## Call sites
- Only caller: tracePathMW L668. path_trace_kernel.cu's sampleDirectGPU is
  the separate RGB implementation (not touched).

## Wavefront integration (next session)
- shadePathSlot: replace the sampleDirectSpectralMW call with A; park the
  NEE POD in a per-slot SoA (or recompute-free local handoff if shadow runs
  fused first-increment); BSDF sampling continues as today.
- New stage_shadow kernel: B->C over slots with valid NEE PODs, atomicAdd
  contribution into color (or non-atomic per-slot add since one slot one
  shadow ray). Lean: traversal + light-emission eval + f eval.
  NOTE: f_spec eval location is a measured tradeoff - if shadow-stage regs
  come out too high from gpu_material_eval_spectral, move f/bsdfPdf eval
  into A (shade already carries material code; costs eval on occluded
  samples). Measure both if needed.
- RNG: A draws from the local curandState seeded by light_seed exactly as
  today - the seed draw stays in shadePathSlot.

## Risks
- lightFront sphere/triangle asymmetry (preserved, document in code).
- The megakernel recomposition must be reviewed for byte-identity (pkg98).
- POD size if parked in SoA: ~64B/slot (ray + floats + ids) - fine.
