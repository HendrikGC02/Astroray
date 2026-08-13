# pkg197 — GPU wavefront denoise-guide AOVs (first-hit albedo + normal + depth)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** open (filed 2026-08-13 — GPU-parity vetted set)
**Estimated effort:** M (register-probe up front; the write itself is small)
**Depends on:** pkg55-C7 wavefront dispatch (`cuda_wavefront_render`); pkg68/pkg70/pkg73
(denoiser backends — all DONE, this feeds them); [[wavefront-shade-kernels-register-saturated]]
(the kernel this touches is register-saturated — probe before committing).

---

## Why this exists (verified line refs, current `main`)

The GPU wavefront render path produces **only** the beauty buffer. `cuda_wavefront_render`
(`module/blender_module.cpp:1836-1846`) returns an `H*W*3` RGB vector that is copied into
`camera->pixels` and nothing else. In contrast, the CPU render loop
(`include/raytracer.h:3173-3174`) writes `cam.albedoBuffer[idx]` and `cam.normalBuffer[idx]`
per pixel from the first-hit shade result. **On the GPU backend those two buffers, plus the
depth buffer, stay zero-filled.**

This breaks three owner-facing things whenever the (default) GPU backend is active:

1. **Denoiser guide quality.** The OIDN/OptiX denoisers (pkg68/pkg70/pkg73, all shipped) take
   albedo + normal *guide* images to preserve edges and texture detail. The addon reads them
   for the denoise path and for Blender's **Denoising Data** passes
   (`blender_addon/__init__.py:4711-4715` — `get_albedo_buffer()`/`get_normal_buffer()`;
   guide-input note at `__init__.py:1067-1070`). On a GPU render these are black, so the
   denoiser runs guide-less — visibly softer/smearier than Cycles, which always has GPU
   guides. This is the concrete "GPU denoising pipeline" parity gap.
2. **The Albedo / Normal / Depth AOVs the addon already advertises** render black on GPU. The
   addon exposes them as first-class AOVs (`blender_addon/__init__.py:199-201`:
   `("albedo",…) ("normal",…) ("depth",…)`), and the `__gpu_features__` honesty dict was
   forced to under-claim because of exactly this
   (`module/blender_module.cpp:4559-4560` — "the GPU path … has no adaptive sampler").
3. **OptiX temporal denoise** (pkg73) needs per-frame guides to hold up across viewport
   orbit; guide-less it degrades to per-frame OIDN.

This is the **cheapest, highest-value slice** of the GPU-AOV gap: albedo/normal/depth are
captured at the **first hit only** (bounce 0), a one-shot global write of values the shade
kernel already has in hand — no per-bounce live state carried through the path. The
register-hostile per-light-path passes (diffuse/glossy/transmission direct/indirect, …) are a
separate, higher-risk package (**pkg198**); do not scope-creep into them here.

## MANDATORY FIRST STEP — register-cost probe (do this before writing the capture)

The wavefront shade kernel is register-saturated: `stageShadeBucketedKernel<P,T,Ph,D>`
(`src/gpu/wavefront/stage_advance.cu:1105`) sits at **REG 254 / STACK 3608 / CONSTANT[0]
1700** for the fleet `<false,false,false,false>` specialization
([[wavefront-shade-kernels-register-saturated]]). The albedo/normal/depth capture is a
**global write of already-computed values at bounce 0** (not carried live state), so the
expectation is near-zero register impact — but that MUST be proven, not assumed:

1. Prototype the first-hit write, build native-sm_120, read the post-link
   `stageShadeBucketedKernel<false,false,false,false>` STACK/REG/CONSTANT via `cuobjdump`
   (NOT `ptxas -v`). HARD gate: **STACK 3608 / REG 254 / CONSTANT[0] 1700 unchanged.**
2. If it spills, prefer capturing in `stageAdvanceKernel` / the intersect stage where the
   first-hit surface data already lives, or gate the write behind a compile-time
   `HasGuideAOVs` axis so the `<…,false>` fleet specialization is byte-identical (the
   pkg184/pkg189 if-constexpr pattern). Report the cuobjdump evidence in the PR either way.

## Scope

- Capture at the **first camera-ray hit** (bounce 0): base-colour albedo, shading normal,
  and hit distance (depth). Match the CPU semantics exactly — `include/raytracer.h:3173-3174`
  for albedo/normal, and the CPU depth/first-hit capture in the same loop — so CPU↔GPU guide
  buffers agree. Sky/miss pixels store the CPU convention (albedo = background/env, normal 0,
  depth 0).
- Plumb the three guide arrays out of `cuda_wavefront_render` and into
  `camera->albedoBuffer` / `camera->normalBuffer` / `camera->depthBuffer` alongside the
  existing beauty copy-back (`module/blender_module.cpp:1842-1846`). Mirror the cryptomatte
  out-param plumbing already there (`cryptoObjOut`/`cryptoMatOut`, lines 1823-1840) — do not
  fork a second copy-back path.
- Normal-buffer convention must match what OIDN/OptiX and the addon Normal AOV expect
  (the CPU `get_normal_buffer` mapping — see pkg75, DONE).

## NOT in scope / do not touch

- **Light-path-expression passes** (diffuse/glossy/transmission direct/indirect, emission,
  environment, AO, shadow, volume) — those are pkg198 (register-hostile, separate probe).
- **Motion vectors** for temporal denoise — CPU-only today (`raytracer.h:3183-3203`,
  pkg72); note it as a follow-up, do not build it here.
- **No CPU behaviour change** — the CPU loop already fills these; leave it byte-identical.

## Acceptance criteria

- [ ] Register probe run and reported FIRST: `stageShadeBucketedKernel<false,false,false,false>`
      stays **STACK 3608 / REG 254 / CONSTANT[0] 1700** (cuobjdump evidence in the PR), or the
      capture is isolated behind a compile-time axis / moved to the intersect stage so the
      fleet specialization is byte-identical.
- [ ] On a GPU wavefront render, `get_albedo_buffer()`, `get_normal_buffer()`, and the depth
      buffer are non-zero and **match the CPU render within a tight per-channel band** on a
      textured/normal-varying reference scene (parity test locks CPU↔GPU guides).
- [ ] A denoise A/B on a **GPU** render at low SPP shows measurably better edge/detail
      retention **with** guides than guide-less (report a metric — e.g. MSE-to-reference or
      an SSIM delta on a fixed scene — not just a screenshot).
- [ ] Blender **Denoising Data** (Denoising Albedo / Denoising Normal) and the addon
      Albedo/Normal/Depth AOVs are populated on the GPU backend (headless Blender 5.1 check).
- [ ] **RTX 5070 Ti hardware gate** (CI has no GPU — [[ci_has_no_gpu_runtime_blindspot]]):
      the above measured on hardware, bound to the exact HEAD, `.pyd` mtime ≥ HEAD.

## Hard non-goals

- No lobe-tagged / per-light-path AOV accumulation (pkg198).
- No lobe-array shrink or shared-state widening to buy register room (pkg178/pkg184 rule —
  if-constexpr isolation only).
- No new denoiser backend — this **feeds** the shipped OIDN/OptiX path, it does not replace it.
