# pkg198 — Light-path-expression render passes (diffuse/glossy/transmission direct+indirect, emission, environment)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** Stage 1 (CPU classification) — done (PR #TBD, 2026-08-14 — sum-to-beauty rel_L1
0.0000, per-channel ratio 1.000/1.000/1.000; isolated-lobe leak <1e-2). Stage 2 (GPU wavefront
mirror + register probe) — **open, probe-first, may-park**.
**Estimated effort:** Stage 1 = M (landed). Stage 2 = L (register-hostile — the up-front probe
decides whether it ships at all).
**Depends on:** Stage 2 depends on Stage 1 (this PR — the CPU reference to mirror) and pkg197
(first-hit guide AOVs — its intersect-stage capture + `__constant__` binding is the template);
[[wavefront-shade-kernels-register-saturated]]; [[closure-graph-lobe-count-spills-fused-kernel]].

---

## Why this exists (premise CORRECTED 2026-08-14 — implementer finding)

The package was filed as "the GPU half of a CPU↔GPU light-path-AOV parity gap: passes work on
CPU, are black on GPU." **That premise was false.** Verified on `main` (grep, whole repo, code
files only):

- `SampleResult.passes` (`include/raytracer.h:1731`) was zero-initialised and **no integrator or
  BSDF ever wrote to it** — the single reference outside the struct definition was the read at
  `include/raytracer.h:3228` (`sPass = ir.passes`), accumulated into `cam.renderPassBuffers`.
- The default integrator `spectral_path_tracer.cpp::sampleFull` filled color/albedo/normal/depth
  but left `r.passes` zero; `pathTraceSpectral` took no pass-output parameter and had no
  first-bounce-lobe / direct-indirect / emission-environment classification.
- The two tests touching these passes used **mocked** renderers returning constant buffers.

So `PASS_DIFFUSE_DIRECT … PASS_ENVIRONMENT` were plumbed end-to-end (registry, Python bindings
`module/blender_module.cpp:2241-2257`, addon viewport selector) but returned **black on BOTH
backends**. This was a whole-feature gap, not a GPU-parity gap — which makes it more valuable to
fix, not less. Coordinator decision (2026-08-14): **Option A**, staged like pkg199 — build the
CPU classification first (Stage 1), then mirror it on the GPU wavefront (Stage 2).

---

## Stage 1 — CPU light-path pass classification  ✅ DONE (this PR)

Implement the classification in the default spectral path tracer so the existing plumbing lights
up: first-bounce lobe category (diffuse/glossy/transmission), direct vs indirect split, and
emission/environment tagging — **citing Cycles** `kernel/film/light_passes.h` +
`integrator/shade_surface.h` (Apache-2.0). Research notes:
`.astroray_plan/docs/pkg198-lightpath-pass-classification-research.md`.

Design (adapted to Astroray's granularity — single combined `evalSpectral`, no per-closure
split, so the coarser single-path-label variant of the Cycles model is used):
- `pathTraceSpectral` gained an optional `outPasses` accumulator; every `color += X` is paired
  with exactly one `passes[p] += X` (total partition → Σpasses == beauty EXACTLY in spectral
  space). Passes carry XYZ (same convention as `SampleResult.color`) and are converted to linear
  sRGB in the render loop with the same matrix as beauty, so the invariant holds in linear sRGB.
- Category locked at the first BSDF interaction (Cycles locks pass weights at bounce 0):
  TRANSMISSION if the sampled `wi` crossed the surface (geometric sign test — no distance/
  sentinel, per [[occlusion-sentinel-as-distance-class-of-bug]]); else GLOSSY for a delta/mirror
  reflection or glossy material; else DIFFUSE. Direct = light gathered before that lock; indirect
  = after. Directly-visible emission → `PASS_EMISSION`; directly-visible background →
  `PASS_ENVIRONMENT`; both fold into `<firstCat>_INDIRECT` after a bounce.

Stage 1 acceptance — all met:
- [x] Σ(light-path passes) == beauty (LINEAR) on an all-lobe scene: per-channel ratio
      `[1.000, 1.00000001, 1.00000001]`, pixelwise rel_L1 `0.0000`.
- [x] Isolated-lobe sanity: pure-diffuse → glossy/transmission < diffuse·1e-2 (measured 0.0);
      metal → diffuse < glossy·1e-2 (measured 0.0); glass → transmission carries the refraction.
- [x] Emission and environment passes populate for directly-visible emitters/background.
- [x] Real-binding tests (`tests/test_pkg198_lightpath_passes.py`) replace reliance on the mocks
      (mocks kept); the two pre-existing `xfail`-gated pass tests in `test_python_bindings.py`
      un-xfailed and passing.

## Stage 2 — GPU wavefront mirror + register probe  (OPEN, probe-first, may-park)

Mirror the Stage-1 classification on the GPU wavefront so the passes agree CPU↔GPU on the
default backend. This is the register-hostile half.

### MANDATORY FIRST STEP — decide feasibility before building
1. Design the GPU pass-accumulation layout against the Stage-1 CPU reference + Cycles film model.
   Per-path pass accumulators are per-hit live state in the shade kernel that is already
   REG-254-saturated. Study whether some passes can be captured OFF the shade kernel (pkg197's
   intersect-stage capture; emission/environment may be accumulatable outside shade).
2. Register-probe the minimal version — carry pass accumulators as SoA global-memory scatter
   (per-pixel pass buffers written incrementally per bounce), so the shade kernel holds pointers,
   not ~10 accumulators. Isolate behind a compile-time `HasLightPassAOVs` axis (pkg184/pkg189
   if-constexpr) so the pass-less fleet specialization is byte-identical by construction.
3. **HARD gate:** `stageShadeBucketedKernel<…,false>` (pass-less) stays at the verified fleet
   baseline **REG 254 / STACK 3352 / CONSTANT[0] 1700** — confirm on the FINAL linked `.pyd` via
   `cuobjdump` (sm_120 confirmed via `--list-elf` first; never `ptxas -v`). NB: **3352 is
   correct**; the earlier `3608` figure in this spec was the stale pre-pkg184/4-axis number —
   pkg190's HW verification re-confirmed 3352 independently.
4. If even the global-scatter form spills the pass-less specialization or regresses non-AOV perf,
   **STOP and park with the cuobjdump evidence** — a clean park is a valid outcome (pkg194
   discipline). The value (a compositor power-user feature) does not justify a fleet-wide
   regression on every GPU render.

### Stage 2 scope (only if the probe clears)
- Fill the same passes on the wavefront, matching Stage-1 CPU semantics; copy-back alongside the
  beauty/guide plumbing established by pkg197 (one path, do not fork).
- Parity gate: CPU vs GPU per-pass per-channel mean-ratio (not SSIM) on the Stage-1 scenes; GPU
  beauty must still equal the sum of the GPU passes (energy closure).
- Non-AOV GPU renders show no perf regression (min-of-N, burn-in — [[gpu-perf-ab-clock-drift]]).
- Headless Blender 5.1: passes populate on the GPU backend and round-trip through the compositor.
- **RTX 5070 Ti hardware gate** ([[ci_has_no_gpu_runtime_blindspot]]), bound to HEAD.

## Hard non-goals (both stages)
- **No lobe-array shrink or shared live-state widening** to buy register room (pkg178/pkg184).
- **No volume passes** until pkg199 lands GPU volumes (`PASS_VOLUME_*` left untouched).
- **No cryptomatte rework** (pkg159) and **no first-hit guide AOVs** (pkg197) — light-path split
  only.
- **Do not force Stage 2 to ship.** A clean park with evidence is a valid, expected outcome.
