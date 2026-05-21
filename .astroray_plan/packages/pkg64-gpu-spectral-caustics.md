# pkg64-gpu — GPU port of spectral SMS caustics

**Pillar:** 3 (light transport) and 5 (GPU)
**Track:** A
**Status:** open — ready to implement
**Estimated effort:** 2-3 weeks (~50 h, multiple sessions)
**Depends on:** pkg64 (CPU SMS, done — PR #230), pkg54/54a/54b (megakernel mirror of `multiwavelength_path_tracer`, done), pkg31 (Sellmeier dispersion, done)

---

## Goal

**Before:** Spectral SMS caustics work on the CPU `path_tracer` (pkg64
Phases 1+2+3, PR #230). On the GPU side, the megakernel
(`src/gpu/path_trace_kernel.cu`, `src/gpu/multiwavelength_kernel.cu`)
contains no SMS dispatch — a scene that renders a prism rainbow on CPU
falls back to brute-force unidirectional path tracing on GPU, producing
no visible caustic at production spp. The per-object `is_caustic_caster`
flag added in pkg64-3 does not cross the CPU→GPU scene upload boundary.

**After:** The CUDA megakernel evaluates the same SMS attempt at every
non-delta vertex, gated by the same `use_refractive_caustics` /
`use_reflective_caustics` integrator params and the same per-object
`is_caustic_caster` flag as the CPU path. The prism-rainbow and
mirror-pool acceptance scenes from pkg64-3 produce a visible caustic on
GPU with receiver-energy ratio ≥ 1.10× and PSNR floor non-regression
matching the CPU gates, and the GPU result tracks the CPU result within
SSIM ≥ 0.97 at the test spp. CPU SMS path is unchanged.

---

## Context

pkg64 (CPU) closed with a 113-line non-goal: *"Do not port to GPU in
this package. SMS GPU port is a follow-up after pkg54."* pkg54 has
shipped (PR series 54/54a/54b). Project owner authorized starting the
GPU port now.

### Fork-point decisions (resolved before filing)

**1. Target the megakernel, not the wavefront pipeline (pkg55).**
pkg55 Phase A.1 landed (PR #257) but Phase B (shade queue + per-material
dispatch) is ~4 weeks out and Phase C (megakernel removal) is ~7 weeks
out. Blocking GPU caustics on Phase C means GPU users get no rainbow
for two months. The CPU pkg64-3 work already factored the SMS attempt
into a single header (`include/astroray/manifold/sms_attempt.h`) that
both integrators call into — that same factoring is what makes the
megakernel port mechanical (one shared device-side header, two call
sites in the integrator hot paths). When pkg55-C deletes the megakernel
the SMS dispatch moves to the wavefront `stage_shade_dielectric` /
`stage_shade_metal` kernels; that re-wire is filed as a follow-up
(see Non-goals). The cost of doing it twice is one ~3-week package now
+ ~1-week wavefront wire-up after pkg55-C, vs. blocking the user for
two months. The owner's "GPU SMS port is a follow-up after pkg54"
direction is the gate that has been cleared.

**2. CLAUDE.md §6 citations: cite the algorithm, not a GPU-specific
implementation.** Zeltner 2020 §4 (Newton + half-vector residual) and
Hanika 2015 §4 (per-wavelength solve) are the algorithmic sources —
those are what get cited at every call site, same as the CPU code. No
published GPU-SMS-on-megakernel reference exists: Zeltner's GPU code
runs on Mitsuba 2 + Enoki/Dr.Jit (JIT-vectorized), which is a different
execution model than hand-written CUDA, and `tizian/specular-manifold-sampling`
does not ship a CUDA port. This package's "port" is therefore a port of
the *math* (one Newton solve + Sellmeier(λ_hero) refraction +
visibility), not a port of an existing CUDA implementation. CLAUDE.md §6
is satisfied because the algorithm citations are unchanged from CPU
pkg64; the warp-divergence cost of putting data-dependent Newton loops
in a megakernel is documented and measured (see Phase 3 acceptance) but
is an implementation property, not an algorithm, and does not require
its own citation. Laine, Karras, Aila 2013 (HPG, DOI
[10.1145/2492045.2492060](https://dl.acm.org/doi/10.1145/2492045.2492060))
is cited in the Lessons section as the framework for interpreting any
measured divergence tax.

**3. `is_caustic_caster` does not exist on the GPU scene today.** Grep
of `include/astroray/gpu_types.h` and `src/gpu/` for `caustic_caster` /
`isCausticCaster` returns zero matches. The flag is set on CPU
`Hittable` via `Renderer::setObjectCausticCaster` (pkg64-3) and stays
CPU-side. The GPU scene-upload path (`module/blender_module.cpp` →
`CUDARenderer::uploadScene`) needs a new boolean field on the
device-side hittable struct, mirrored from CPU at upload time, and the
per-object update path needs to re-upload (or patch) on
`set_object_caustic_caster` calls between renders. Scope is in this
package.

**4. Validation gates pinned to CPU pkg64-3 numbers, plus a GPU/CPU
parity gate and a speedup target.** The CPU Phase 3 verification
measured receiver-energy ratio 1.18× (gate ≥ 1.10×), PSNR floor delta
+0.26 dB (gate ≥ −0.5 dB), and empty-hook overhead 2.0% (gate ≤ 5%) on
RTX 5070 Ti / Windows MSVC `build_cuda`. The GPU port re-uses those
gates *and* adds an SSIM ≥ 0.97 GPU-vs-CPU parity gate (matching pkg54b
NIR-band SSIM tolerance, which accounts for the FP-noise envelope
characterized in pkg82). Speedup target is conservative: GPU SMS megakernel
≥ 5× faster than CPU SMS at 256 spp on the prism scene — CPU SMS at the
pkg64-3 acceptance spp is ~1 s per 64×64 frame, the megakernel mirror of
the spectral path tracer landed pkg54 well inside the 5× envelope, and
SMS is a per-non-delta-vertex local addition with similar per-ray cost
to dielectric refraction, so 5× is a floor not a stretch. If the
measured speedup is < 3×, file a follow-up on the warp-divergence cost
before adding more SMS surface area.

---

## Reference

### Internal

- pkg64 spec: [`pkg64-spectral-caustics.md`](pkg64-spectral-caustics.md) — parent CPU package.
- Caustics research note: [`../docs/caustics-research.md`](../docs/caustics-research.md) — algorithm + license analysis (BSD-3 SMS code skeleton, Hanika 2015 paper math).
- CPU SMS attempt header: `include/astroray/manifold/sms_attempt.h` — single source of truth for the Newton + refraction + Schlick + visibility chain; the device-side port mirrors this exactly.
- CPU integrators wiring the hook: `plugins/integrators/spectral_path_tracer.cpp`, `plugins/integrators/sms_caustic_path_tracer.cpp`, `include/raytracer.h` (`pathTraceSpectral`'s `SMSHook` callback).
- CPU per-object plumbing: `Renderer::setObjectCausticCaster`, Python binding `Renderer.set_object_caustic_caster` in `module/blender_module.cpp`.
- GPU megakernel targets: `src/gpu/path_trace_kernel.cu` (RGB), `src/gpu/multiwavelength_kernel.cu` (spectral). The spectral kernel is the primary target because the prism rainbow lives in the spectral integrator.
- GPU types: `include/astroray/gpu_types.h` — GHitRecord, GMaterial, GSampledWavelengths. Needs a new `bool isCausticCaster` field on the device hittable (or material — pick at implementation time; CPU has it on `Hittable`).
- pkg55 wavefront: [`pkg55-wavefront-soa-refactor.md`](pkg55-wavefront-soa-refactor.md) — informs Non-goals (do not touch wavefront).
- pkg82 SSIM variance note: [`pkg82-pkg54c-gate-variance.md`](pkg82-pkg54c-gate-variance.md) — explains why the GPU/CPU parity gate is set at 0.97, not 0.999.

### External (read for understanding only — no code mirrored)

- Zeltner, Georgiev, Jakob 2020 — SMS Newton solve, §4.2 (single-vertex residual). DOI [10.1145/3386569.3392408](https://doi.org/10.1145/3386569.3392408). The CPU code already cites this; the GPU code cites the same locations.
- Hanika, Droske, Manakov 2015 — per-wavelength Newton residual, §4. DOI [10.1111/cgf.12681](https://doi.org/10.1111/cgf.12681).
- Laine, Karras, Aila 2013 — "Megakernels Considered Harmful." DOI [10.1145/2492045.2492060](https://doi.org/10.1145/2492045.2492060). Cited in Lessons for the warp-divergence framework if the measured speedup misses the 5× floor.

---

## Specification

### Phase 1 — device-side SMS attempt header + per-object flag plumbing (~1 week)

**Goal:** Mechanical port of `include/astroray/manifold/sms_attempt.h`
to a `__device__`-callable equivalent, plus the per-object caster flag
crossing the GPU scene-upload boundary. No integrator wiring yet — this
phase produces a callable device function and a verifiable upload path,
nothing more.

#### Files to create

| File | Purpose |
|---|---|
| `include/astroray/manifold/sms_attempt_device.cuh` | `__device__` port of `runSMSAttempt`. Mirrors the CPU header line-for-line (Newton iteration, Sellmeier(λ_hero), Schlick Fresnel, visibility) using device-side types (`GHitRecord`, `GSampledWavelengths`, `gpu_bvh_hit`). Cites Zeltner 2020 §4.2 and Hanika 2015 §4 at the same code lines as the CPU header. |
| `tests/test_pkg64_gpu_sms_attempt_unit.py` | Subprocess test: render a single-ray scene through a device entry point that calls `runSMSAttemptDevice` directly, compare the returned hero-channel contribution to the CPU `runSMSAttempt` output on the same ray. Tolerance: per-ray relative error ≤ 1e-3 (FP noise envelope; tighter than the SSIM gate because this is a single-ray comparison). |

#### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_types.h` | Add `bool isCausticCaster` to the device hittable struct (matching CPU `Hittable::isCausticCaster_`). One bool, no flag-packing — the gate selectivity dominates and a single bool keeps the diff small. |
| `src/gpu/cuda_renderer.cu` (or wherever scene upload lives) | Copy the CPU `Hittable::isCausticCaster()` value into the device struct during `uploadScene`. |
| `module/blender_module.cpp` | `set_object_caustic_caster` already mutates CPU state; add a "scene dirty" mark so the next `render` re-uploads the affected object's flag (or patch in place — implementation detail). |

#### Phase 1 acceptance

- [ ] `runSMSAttemptDevice` callable from a host test harness, returns the same hero-channel spectrum as the CPU `runSMSAttempt` on the BK7-sphere acceptance ray (rel err ≤ 1e-3).
- [ ] `is_caustic_caster=True` set on CPU survives a render round-trip on GPU (verified by reading back the device hittable struct via a debug kernel; not a production code path).
- [ ] No regression on existing GPU tests (`pytest tests/ -k gpu`).

### Phase 2 — megakernel integration (~1 week)

**Goal:** Wire the device SMS attempt into `multiwavelength_kernel.cu`
at each non-delta vertex, gated by `use_refractive_caustics` /
`use_reflective_caustics` integrator params and the per-hit
`isCausticCaster` flag. Add the same `use_reflective_caustics` /
`use_refractive_caustics` controls to the GPU integrator-param surface
that CPU has.

#### Files to modify

| File | What changes |
|---|---|
| `src/gpu/multiwavelength_kernel.cu` | At each non-delta vertex, check `(use_caustics_flag && hit.material.isCausticCaster)`; if true, call `runSMSAttemptDevice` and add the returned spectrum to the accumulating radiance. Mirror the CPU additive-MIS-with-disjoint-strategies pattern documented in `include/raytracer.h`. |
| `src/gpu/path_trace_kernel.cu` | Same wiring for the RGB megakernel (CPU pkg64-3 supports both RGB and spectral with the same hook; do not regress that). |
| `plugins/integrators/spectral_path_tracer.cpp` | `renderGPU()` plumbs `use_refractive_caustics` / `use_reflective_caustics` integrator params to the kernel launch. |
| `plugins/integrators/path_tracer.cpp` | Same plumbing on the RGB GPU path. |

#### Phase 2 acceptance

- [ ] Empty-hook (no caster flagged) GPU output is bit-equal to pre-pkg64-gpu GPU output on the pkg54 cornell parity scene. (Matches the CPU pkg64-3 non-regression test convention.)
- [ ] Empty-hook GPU walltime overhead ≤ 5% on the pkg54 cornell parity scene at 64 spp. (Matches the CPU empty-hook cost gate.)
- [ ] CUDA build green on `windows-cuda-vs-release` preset; no new warnings on the modified kernels.

### Phase 3 — acceptance gates on the prism + mirror-pool scenes (~1 week)

**Goal:** Re-run the pkg64-3 acceptance scenes on GPU, plus the new
GPU/CPU parity gate and speedup gate. Numbers committed to the spec
Lessons section, same format as pkg64-3 Phase 3 hardware verification.

#### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg64_gpu_phase3_default_integrator.py` | GPU equivalent of `test_pkg64_phase3_default_integrator.py`: prism scene with BK7 caster, asserts receiver-energy ratio ≥ 1.10× and PSNR floor delta ≥ −0.5 dB on GPU. |
| `tests/test_pkg64_gpu_phase3_no_regression.py` | GPU equivalent of the no-regression test: empty hook is bit-equal to pre-pkg64-gpu and cost gate ≤ 5%. |
| `tests/test_pkg64_gpu_cpu_parity.py` | New: GPU SMS vs CPU SMS SSIM ≥ 0.97 on the prism scene at 256 spp; informational receiver-energy GPU/CPU ratio printed. |

#### Phase 3 acceptance

- [ ] **Receiver-energy ratio (gate ≥ 1.10×):** measured on RTX 5070 Ti, prism BK7 scene at the same spp as CPU pkg64-3. Number recorded in Lessons.
- [ ] **PSNR floor delta (gate ≥ −0.5 dB):** same scene, same spp.
- [ ] **Empty-hook walltime overhead (gate ≤ 5%):** cornell parity scene, same as Phase 2.
- [ ] **GPU/CPU SSIM parity (gate ≥ 0.97):** prism scene at 256 spp. Threshold rationale: matches pkg54b NIR-band tolerance, accounts for the FP-noise envelope characterized in pkg82. A tighter gate is not justified until pkg82 measures cross-build variance specifically for the SMS code path.
- [ ] **Speedup floor (gate ≥ 5× vs CPU SMS):** prism scene at 256 spp on RTX 5070 Ti, end-to-end render walltime. If < 3× measured, STOP and file a follow-up on warp-divergence cost (Laine 2013 framework).
- [ ] **Register pressure (non-regression vs pkg55-A.0 baseline):** measured via `--ptxas-options=-v` on the production CUDA build, the megakernel with SMS enabled must report:
  - `regs/thread ≤ 180` (pkg55-A.0 baseline: 158 regs/thread; allows for SMS Newton + 2 BVH visibility traces without breaking occupancy)
  - `active blocks/SM ≥ 1` (matches pkg55-A.0 baseline — no further occupancy regression)

  Rationale: pkg55-A.0 documented the megakernel at the 1-block/SM warp-occupancy cliff. SMS Newton inline could spike registers further. The empty-hook 5% perf gate does not catch a regs spike because empty-hook short-circuits before Newton runs. Compare against `benchmarks/wavefront/baseline.json` numbers. Source: `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` §Phase A.0 (158 regs/thread, 1 active block/SM baseline).
- [ ] STATUS.md updated.

---

## Acceptance criteria (summary)

| Gate | Threshold | Source |
|---|---|---|
| Receiver-energy ratio | ≥ 1.10× | CPU pkg64-3 strict gate |
| PSNR floor delta | ≥ −0.5 dB | CPU pkg64-3 floor |
| Empty-hook walltime overhead | ≤ 5% | CPU pkg64-3 cost gate |
| GPU vs CPU SMS SSIM | ≥ 0.97 | pkg54b NIR + pkg82 variance envelope |
| GPU SMS speedup vs CPU SMS | ≥ 5× (floor); < 3× triggers follow-up | conservative target, prism scene 256 spp |
| Single-ray GPU/CPU attempt rel err | ≤ 1e-3 | Phase 1 unit test, FP noise |

---

## Non-goals

- **Do not re-implement the CPU SMS path; only port.** The device header mirrors `include/astroray/manifold/sms_attempt.h` line-for-line. If the port diverges from the CPU algorithm, that's a bug to fix in this package, not a feature.
- **Do not touch pkg55 wavefront code; that's a follow-up if pkg55-C removes the megakernel target.** When pkg55-C lands, the SMS dispatch in `multiwavelength_kernel.cu` and `path_trace_kernel.cu` needs to move to the wavefront `stage_shade_*` kernels. File that as a follow-up package at pkg55-C close-out, not in this PR.
- **Do not invent a GPU-specialized SMS variant.** No batched-Newton-warp-collapse, no in-flight queue compaction, no caustic-photon hybrid. CLAUDE.md §6: published algorithm only. If the warp-divergence cost is unacceptable, the answer is to file a follow-up citing a published divergence mitigation (e.g. persistent threads, work-stealing), not to invent one.
- **Do not change the CPU SMS path.** The CPU acceptance tests must continue to pass byte-equivalently. Any "while I'm here" refactor on the CPU side is out of scope.
- **Do not implement glint rendering on GPU.** Same scope boundary as CPU pkg64.
- **Do not couple this to Pillar 4 / GR rendering.** Curved-spacetime caustics remain out of scope.
- **Do not add new integrator-param surface beyond what CPU has.** `use_refractive_caustics`, `use_reflective_caustics`, per-object `is_caustic_caster` — that's the full surface, same as CPU.

---

## Progress

Phase 1 — device-side header + flag plumbing:
- [x] `include/astroray/manifold/sms_attempt_device.cuh` ported from CPU
  header with line-matched citations. **Architect post-Phase-1 audit:
  zero algorithm-level divergences — every numeric step BIT-FAITHFUL vs
  merged CPU `sms_attempt.h`/`newton_iterate.h`/`half_vector_constraint.h`
  (PR #230).** Monomorphized for the sphere caster (std::function Newton
  callbacks inlined); `std::mt19937` → explicit `(r1, r2)`;
  `dynamic_cast`/virtual → device types.
- [x] Caster flag field added on **`GSphere`** (not a generic
  `GHittable` — the GPU scene has no per-object base struct; sphere-only
  caster scope matches CPU pkg64 Phases 1-3 and the spec's "or material
  — pick at implementation time"); `scene_upload.cu` mirrors
  `sph->isCausticCaster()`. No scene-dirty flag added: `render()` /
  `upload_scene()` call `uploadScene()` unconditionally and
  `scene_upload.cu` re-reads the flag fresh every upload (spec
  explicitly sanctions "patch in place"; pkg56 geometry-uploader path
  verified to also re-push `d_spheres`). Comment-not-code per
  CLAUDE.md §2/§3 — architect-confirmed CORRECT call.
- [ ] `tests/test_pkg64_gpu_sms_attempt_unit.py` — gate authored
  (rel err ≤ 1e-3, subprocess+skip convention); **/verify-deferred**:
  the probe harness (probe `.cu` + host wrapper + `ASTRORAY_CUDA_SOURCES`
  CMake entry + `cuda_renderer.cu` env hook +
  `build_bk7_sms_acceptance_scene` helper) is uncompilable by the
  implementing agent (no vcvars in tools; CI has no GPU) and is the
  remaining Phase 1 work, to be wired + run on the RTX box.
- [ ] No regression on `pytest tests/ -k gpu` — /verify-deferred (GPU
  build required).

**Cadence — OWNER DECISION 2026-05-18: Option B.** Phase 1 *core* lands
as its own PR and is `/verify`-ed on RTX before Phase 2 is written, so
the GPU caustic stack is not built blind on an unverified
Newton/refraction core (latent-bug risk compounds multiplicatively
across 3 coupled uncompilable phases). Phase 2 (megakernel integration)
and Phase 3 (acceptance gates) are follow-up PRs against the verified
Phase 1 base, each preceded by an architect checkpoint.

Phase 2 — megakernel integration:
- [ ] `multiwavelength_kernel.cu` calls `runSMSAttemptDevice` at non-delta vertices
- [ ] `path_trace_kernel.cu` likewise (RGB path)
- [ ] Integrator-param plumbing on `spectral_path_tracer.cpp` + `path_tracer.cpp` `renderGPU()`
- [ ] Empty-hook bit-equal + ≤ 5% cost gate measured

Phase 3 — acceptance + numbers:
- [ ] `test_pkg64_gpu_phase3_default_integrator.py` — receiver-energy ratio + PSNR floor
- [ ] `test_pkg64_gpu_phase3_no_regression.py` — empty-hook bit-equal + cost gate
- [ ] `test_pkg64_gpu_cpu_parity.py` — SSIM ≥ 0.97
- [ ] Speedup floor measured on RTX 5070 Ti; numbers in Lessons
- [ ] STATUS.md updated

---

## Lessons (filled in on completion)

*(empty until done)*

### Hardware verification 2026-05-21 — PR #323 Phase 1 core

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 595.97, compute cap 12.0  
**OS:** Windows 11 Enterprise 10.0.26200  
**CUDA:** 12.8.61  
**OptiX:** 9.1.0  
**Compiler:** MSVC 19.44.35208.0  
**Worktree:** `C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\.claude\worktrees\pkg64-gpu`  
**HEAD:** `2a092b4` (2026-05-18 20:06:08 +1000)  
**Build:** `.pyd` mtime 2026-05-21 22:19:02 (fresh, post-HEAD)

#### Phase 1 acceptance gates

| Gate | Status | Details |
|------|--------|---------|
| **Gate 1:** `runSMSAttemptDevice` callable, hero rel err ≤ 1e-3 vs CPU | **BLOCKED** | Probe harness not present. `tests/test_pkg64_gpu_sms_attempt_unit.py::test_pkg64_gpu_sms_attempt_matches_cpu` skipped with message: "pkg64-gpu Phase 1 probe hook not present in this build. Phase 1 CORE (sms_attempt_device.cuh + GSphere.isCausticCaster + scene_upload mirror) has landed; the probe harness (probe .cu + host wrapper + cuda_renderer env hook + build_bk7_sms_acceptance_scene helper) is the /verify-deferred remainder." |
| **Gate 2:** `is_caustic_caster=True` survives upload round-trip | **BLOCKED** | Probe debug-readback hook not present. `tests/test_pkg64_gpu_sms_attempt_unit.py::test_pkg64_gpu_caster_flag_crosses_upload` skipped (same reason as Gate 1). |
| **Gate 3:** No regression on `pytest tests/ -k gpu` | **PASS** | 40 passed, 4 skipped (2 pkg64-gpu probes + 2 unrelated), 1 xfailed (pre-existing CPU/GPU SSIM diagnostic), 1018 deselected. No failures. |

#### Core Phase 1 changes verified present

1. **Device header:** `include/astroray/manifold/sms_attempt_device.cuh` exists, contains `__device__` port with Zeltner 2020 §4.2 citations.
2. **GSphere.isCausticCaster field:** `include/astroray/gpu_types.h` line 253 declares `bool isCausticCaster = false`.
3. **Scene upload mirror:** `src/gpu/scene_upload.cu` line 290 copies `sph->isCausticCaster()` to `gs.isCausticCaster`.
4. **Python binding:** `Renderer.set_object_caustic_caster` binding present (from pkg64-3), confirmed via smoke-check.

#### Probe harness status (Phase 1 /verify-deferred)

The following components required to run Gates 1 and 2 are **not present** in PR #323:

- `build_bk7_sms_acceptance_scene` Python helper function (test line 96 imports it from `astroray` module)
- `ASTRORAY_PKG64_GPU_SMS_PROBE` env-var hook in `cuda_renderer.cu` (test line 106 sets this)
- Probe device kernel that calls `runSMSAttemptDevice` and emits stderr line `[pkg64-gpu] sms attempt probe: ok=... fhero=... fhero_cpu=... caster_flag_crossed=...`

The test file's subprocess (line 90-112) fails at import: `ModuleNotFoundError: No module named 'astroray'` when run in the subprocess environment, but more fundamentally the helper function does not exist in the module's namespace.

This matches the memory note [[pkg64-gpu-blockers-stale-option-b]] expectation: "Phase 1 probe-harness wiring (probe .cu, host wrapper, ASTRORAY_CUDA_SOURCES CMake entry, cuda_renderer.cu env hook, build_bk7_sms_acceptance_scene helper) may not have landed in PR #323."

#### Visual inspection

No PNG outputs produced (Phase 1 tests are unit/upload parity, not visual render tests).

#### Overall verdict for PR #323 Phase 1

**Phase 1 CORE changes: VERIFIED PRESENT**  
The device header, GSphere.isCausticCaster field, and scene_upload.cu mirror are all in place and build cleanly.

**Phase 1 acceptance gates: BLOCKED (probe harness deferred)**  
Gates 1 and 2 cannot be run without the probe harness. The test file explicitly handles this with skips (not false passes), correctly identifying the missing components.

**GPU regression gate: PASS**  
No regressions on the existing 40 GPU tests.

**Recommendation:**  
PR #323 Phase 1 core is **build-clean and regression-free**. Gates 1 and 2 require the /verify-deferred probe harness. The spec notes this is expected (Phase 1 acceptance comment: "not a production code path" for the debug readback). If the probe harness is intended to land in a follow-up commit or PR, schedule a second verification run once it's pushed. If the probe was intended to be part of PR #323, it is missing.

#### Anomalies

None observed. Build warnings (double→float conversions in raytracer.h, shapes.h) are pre-existing, not introduced by PR #323.
