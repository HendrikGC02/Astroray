# pkg197 — GPU wavefront denoise-guide AOVs (first-hit albedo + normal + depth)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** done (PR #608, 2026-08-13 — intersect-stage capture; shade kernel byte-identical REG 254/STACK 3352/CONSTANT[0] 1700; CPU↔GPU albedo exact, depth ±3%, same-surface normal cos 0.9998; GPU OIDN A/B +8.0% edge-MSE)
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

---

## Hardware verification 2026-08-13 (PR #608, independent re-measurement)

**Hardware:** NVIDIA GeForce RTX 5070 Ti (16303 MiB), driver 610.47, Windows 11
Enterprise 10.0.26200. CUDA 12.8.61 (nvcc V12.8.61, cuda_12.8.r12.8). Compiled
features: oidn_denoiser True, optix_denoiser True, cuda True, wavefront_cuda
True, spectral_gpu_materials True.

Verified in the implementer worktree Astroray-pkg197 (branch pkg197), HEAD
934c37b971f7e68e88b63fe16ad691474961f12f. Branch NOT rebased/pushed by the
verifier (freeze respected). The .pyd was foreground-rebuilt via
build_cuda_worktree.bat before verification; the only commit newer than the
pre-existing .pyd (934c37b, lint - import grouping) touches only
tests/test_pkg197_gpu_guide_aovs.py, not a build input, so the rebuild
correctly produced no binary change (confirmed via cuobjdump numbers below).
list-elf confirms sm_120 embedding.

### 1. Register hard gate -- PASS, byte-identical to main

Independently rebuilt main (HEAD ab4152b0a957d85f8254ca8868c857ed132aebfe at
verification time) from clean in the primary checkout and ran
"cuobjdump -res-usage" on both .pyd files for direct comparison (not just
trusting the PR's self-reported numbers):

| Kernel | main | pkg197 (PR #608) |
|---|---|---|
| stageShadeBucketedKernel<false,false,false,false> | REG:254 STACK:3352 SHARED:0 LOCAL:0 CONSTANT[0]:1700 | REG:254 STACK:3352 SHARED:0 LOCAL:0 CONSTANT[0]:1700 |
| stageIntersectQueuedKernel (the actual intersect-stage kernel -- intersectPathSlot is an inlined device fn, reports REG:0/STACK:0 on both) | REG:127 STACK:616 SHARED:0 LOCAL:0 CONSTANT[0]:1680 | REG:127 STACK:616 SHARED:0 LOCAL:0 CONSTANT[0]:1680 |

Byte-identical on both kernels. Note: the spec's MANDATORY FIRST STEP section
above states the fleet baseline as STACK 3608; the verified current main
baseline is STACK 3352 (3608 is stale -- apparently superseded by an
unrelated main-branch change before pkg197 branched; not something pkg197
caused or should be blamed for). The PR's self-reported STACK 3352 is correct
against current main, confirmed independently.

### 2. CPU-GPU guide parity -- PASS

96x96 sphere-on-floor scene (red Lambertian sphere r=1.2, blue Lambertian
floor), 48 spp, linear (apply_gamma=False). Independently re-measured (not
reusing the PR's numbers):

    shared hits: 6149 / 9216
    albedo GPU mean: [0.5176532  0.37782568 0.45678163]
    albedo CPU mean: [0.51300216 0.37961456 0.461075  ]
    albedo per-channel ratio: [1.0090663  0.99528766 0.9906883 ]   (gate: [0.92, 1.09])
    depth GPU mean: 4.647839  depth CPU mean: 4.631642  ratio: 1.0034971   (gate: [0.97, 1.03])
    same-surface pixels: 5634
    normal cosine mean (same-surface): 0.99975115  min: 0.9969549  max: 1.0000002   (gate: mean > 0.99)
    normal cosine mean (all shared): 0.98596895  median (all shared): 1.0

All within gate bands; consistent with the PR's claimed numbers (ratio bands,
0.9998 mean cosine).

Anomaly (informational, not a regression): spec prose above states "Sky/miss
pixels store the CPU convention (albedo = background/env, normal 0, depth
0)." Measured: CPU albedo at miss pixels = [0,0,0] (not the background color
[0.5,0.6,0.7]), and GPU matches it exactly ([0,0,0]). Traced to
raytracer.h:1699 (Vec3 albedo{0} default, never reassigned to background on a
miss in the current CPU loop) -- this is a pre-existing CPU behavior, not
something pkg197 introduced; GPU correctly mirrors actual CPU behavior (true
parity), just not the specific prose in this spec. Flagging for spec-text
correction, not a gate issue.

### 3. Denoise A/B (GPU render + OIDN) -- PASS

Edge-band (top-10%-gradient pixels) MSE-to-256spp-reference on an 8spp GPU
render, same scene/seed, guided vs guideless:

    guided=0.001491  guideless=0.001621  improvement=8.0%

Matches the PR's claimed numbers exactly (same seed, same build -- reproduced
via "pytest tests/test_pkg197_gpu_guide_aovs.py::test_gpu_denoise_guides_beat_guideless -v -s").
Side-by-side PNG saved to test_results/pkg197_denoise_guides_ab.png (guideless
| guided | reference). Visual inspection: no fireflies, no NaN/magenta/black
speckle, no banding; all three panels show a clean sphere/floor silhouette;
guided panel is subtly cleaner than guideless, consistent with the 8% MSE
improvement. Also independently rendered and inspected the raw
albedo/normal/depth guide buffers directly
(test_results/pkg197_verifier_guides_viz.png): albedo shows correct
red-sphere/blue-floor separation, normal shows a smooth RGB gradient sphere
with correct up-vector floor normal, depth shows a smooth gradient with no
NaN/Inf (np.isnan/np.isinf checked False on all three buffers).

### 4. applyPasses GPU-route scope addition -- PASS

Independently rebuilt main and ran identical fixed-seed (seed 4242) GPU
renders on both main and pkg197 builds:

- No-passes byte-identity: pkg197 (no passes registered) vs main (no
  applyPasses call exists) -- max abs pixel diff = 1.1920929e-07 (single-ULP
  float32 noise from GPU atomic-add ordering, not a real difference;
  np.array_equal is False but the diff is at machine epsilon). Confirms the
  "if (passes_.empty()) return;" guard in Renderer::applyPasses makes plain
  GPU renders MC-noise-equivalent to main's un-touched-by-#608 path.
- Denoiser now actually runs on GPU: main GPU render with
  add_pass("oidn_denoiser") vs main GPU render with no pass -- max abs diff
  1.19e-07 (denoiser pass silently never executes on main's GPU route,
  confirming the pre-#608 bug described in the PR). pkg197 GPU render with
  the same pass vs pkg197 no-pass -- mean abs diff 0.0281, max 0.394 (real
  denoising occurred). This directly confirms criterion 5's two halves: plain
  GPU unaffected, use_denoising now actually denoises on GPU where main
  silently didn't.

### 5. Test suite -- PASS (gate scope), pre-existing unrelated xfails noted

tests/test_pkg197_gpu_guide_aovs.py -v -s --tb=short --runxfail: 4 passed
(test_gpu_guides_populated, test_cpu_gpu_guide_parity,
test_gpu_guide_toggle_off_zeroes, test_gpu_denoise_guides_beat_guideless).

PR-claimed regression sweep (cryptomatte incl. GPU roundtrip, normal-buffer,
texture parity, OIDN, AOV passes, photon wavefront, dispersion, shade-smooth,
OptiX, motion-vector, viewport-progressive, spectral-gpu, compositor-denoise,
gpu-features guard), run together with --runxfail:

    78 passed, 1 skipped, 1 failed (test_gpu_shade_smooth.py::test_cpu_gpu_shade_smooth_ssim_diagnostic)

The 1 failure is a pre-existing xfail-marked diagnostic
([[ssim-wrong-gate-for-independent-rng]]) -- verified byte-identical
(SSIM=0.7343) on freshly rebuilt main, i.e. not affected by pkg197 in any way.

A broader, over-inclusive sweep additionally run against the full
tests/test_python_bindings.py (not part of the PR's claimed set -- verifier's
own extra due-diligence) surfaced 16 failures under --runxfail; 14 were
confirmed byte-identical pre-existing xfail(strict=False) failures on freshly
rebuilt main (unrelated feature areas: transparent film/glass alpha,
glossy/transmission bounce toggles, filter_glossy, emission pass isolation,
component-pass sum, HDR preservation, world volume fog, gamma toggle,
cryptomatte buffer shape). The remaining 2
(test_disable_reflective_caustics_reduces_mirror_caustic_outliers,
test_disable_refractive_caustics_reduces_glass_caustic_outliers) are also
pre-existing xfail(strict=False, reason="caustics flags not ported to the
spectral path_tracer -- deferred") and were shown to be RNG-flaky on both
builds -- 4 repeated runs on pkg197 alone produced FF / F. / .. / F.
(pass/fail flip run to run); these tests never call set_seed, so each render
uses std::random_device per [[seed-zero-is-random-sentinel]]. None of the 16
are attributable to pkg197.

### Verdict: HW PASS
