# batchH item 3 — pkg265 Phase 3 GPU glass walk — WIP STATE (2026-09-13)

Branch: feat/batch-h2-pkg265-gpu-walk (from feat/batch-h-gpu-shade-stage / PR #811).
Status: NOT all-gates-green. Per the brief, NO PR opened. This is a running-start WIP.

PR #811 (items 1+2) is the shipped deliverable; item 3 is parked here.

## What is DONE
- `include/astroray/gpu_microsurface_dielectric.cuh` (new, self-contained, DCE'd
  because unused → fleet build unaffected): device twin of the host-only `msdiel`
  namespace. Ported 1:1 from `include/astroray/microsurface_dielectric.h`:
  HashRng (splitmix64+PCG32), C1/invC1 (device erff/erfinvf — NOT the CPU Giles
  approximation), lambdaGGX, sampleHeight, sampleVNDF, fresnelDielectric,
  refractMicro, sampleWalk (__noinline__), stochasticEval (__noinline__),
  stochasticEvalHashed. Design source: pkg265 research note §"Phase 3 (GPU walk)".

## MUST-VERIFY before trusting (CLAUDE.md §6 — do NOT ship my reconstruction)
- `vndfDwi` / `reflLobe` / `refrLobe` in the new header are my RECONSTRUCTION of
  the CPU `microsurface_dielectric.h` lobes at lines ~334-386 (I read their
  signatures + stochasticEval usage but NOT the full bodies). Port them
  EXACTLY from the CPU header and diff a few (wo,wi,alpha,ior) points
  host-vs-device before wiring — a wrong lobe silently biases eval. Everything
  above them (sampleWalk, sampleHeight, VNDF, Fresnel, refract, hashing) is a
  faithful 1:1 port and can be trusted after a compile.

## Remaining ROUTING (not yet done)
1. Publish a runtime flag `__constant__ int c_gpuGlassWalk` in
   src/gpu/wavefront/stage_advance.cu (mirror `c_hasHair` at line ~218) +
   `setWavefrontGlassWalkEnabled(bool)` (mirror `setWavefrontHairEnabled`, ~2801)
   + a `SceneUploadResult::hasGlassWalk` field (set when any material is a rough
   dielectric / transmissive Principled with roughness>~0.08) published in
   gpu_wavefront_snapshot.cu (next to `setWavefrontHairEnabled(res.hasHair)`, ~1561).
2. `#include "gpu_microsurface_dielectric.cuh"` in gpu_materials.h.
3. SAMPLE: replace the #771 dead-sample delta reroute in
   `gpu_pr_chooseAndSampleDir` transmission branch (gpu_materials.h ~2749-2785):
   when `c_gpuGlassWalk` AND rough, build a local frame oriented so woLocal.z>0
   (t = normalize(rec.tangent − nOr·(rec.tangent·nOr)), b = nOr×t; alpha
   isotropic), call `gpu_msd::sampleWalk(woLocal, alpha, ior, entering, rng, 16)`,
   map wi back to world, set ds.ok/ds.wi, carry radianceScale into f/pdf. Keep the
   delta branch for α→0 and the rare dead-sample fallback.
4. EVAL (the consistency trap — do NOT skip): `gpu_closure_graph_sample`'s
   non-delta branch re-evaluates `gpu_closure_graph_eval`, so route the
   transmission lobe of `gpu_closure_graph_eval` (gpu_materials.h ~2981) AND
   `gpu_closure_graph_eval_spectral` (~3063) through
   `gpu_msd::stochasticEvalHashed` (magnitude-factored for the JH albedo clamp,
   as CPU DisneyPlugin::evalSpectral does), gated on `c_gpuGlassWalk`. pdf stays
   the §9 firstBouncePdf proxy (already the GPU transmission pdf).

## BUILD + GATES (multi-build, all under the GPU lock)
- Build: `python scripts/build/gpu_locked_build.py <ABS worktree>
  "scripts\\build\\build_cuda_nosccache.bat" batchH2` (double-quoted DOUBLE
  backslashes — forward slashes make cmd fail "'scripts' is not recognized"; a
  nohup/& detaches and false-exits at exit 0).
- HARD REG GATE: cuobjdump --dump-resource-usage on the built .pyd →
  `stageShadeBucketedKernel` must stay REG:254, LOCAL:0 (0 spill) on ALL 128
  specialisations. The __noinline__ walk/eval behind the runtime flag is the
  zero-fleet-cost pattern; if any specialisation spills, the walk state leaked
  into the caller — check the flag gating / that __noinline__ took.
- Un-xfail (verify with --runxfail; memory xfail-gated-features-must-unxfail):
  - tests/test_pkg265_lit_furnace.py::test_principled_lit_furnace_conserves_gpu
    (~line 97): strict xfail. HEAD (#771 stub) reads r0.2 0.9958, r0.5 0.9688,
    r0.85 0.9612, r1.0 0.9570; CPU walk 0.9936-0.9964. Gate: GPU furnace 0.97..1.02.
  - tests/test_pkg188_transmission_colour_upsample_parity.py coat_over_tinted_glass
    (~line 79): strict xfail; GPU/CPU R 1.26 on the stub, band [0.95,1.05].
- Parity: CPU-vs-GPU per-channel ROI mean ratio ±5% on the pkg263 glass sphere
  (memory ssim-wrong-gate-for-independent-rng — mean ratio, NOT SSIM). Save a
  contact sheet under test_results/pkg265_phase3/.
- Perf: pkg81 wavefront within noise (memory gpu-perf-ab-clock-drift, min-of-N).

## Estimate
~2-3 build/probe cycles (register tuning is the risk) + the gate sweep. The design
note says explicitly this is its own multi-build lane, which is why PR #811 (items
1+2) shipped first and this is parked as WIP.
