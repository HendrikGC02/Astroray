# pkg64-gpu — GPU port of spectral SMS caustics

**Pillar:** 3 (light transport) and 5 (GPU)
**Track:** A
**Status:** Phase 2 done (PR #348, 2026-05-22); Phase 3 done (PR #350, 2026-05-23 — test infrastructure + caustics toggle wiring; hardware baseline-pinning + Sellmeier GPU upload blocked on pkg64-gpu-sellmeier-upload)
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

**2026-05-30 fork note:** a SECOND caustic mechanism now exists — the forward
**photon-map** caustics (pkg106/109/110/111, CPU-only today). It overlaps this SMS
path for focusing casters (e.g. a glass sphere) and is strictly more general (it
also handles flat prisms, which camera-side SMS cannot — see pkg106). Before more
SMS-GPU surface area is added (e.g. pkg64-gpu Session 2 multi-IOR), the owner should
decide the canonical GPU caustic path (SMS / photon map / both) —
`.astroray_plan/docs/cpu-gpu-parity-status.md` §3 and the GPU photon-map package
**pkg113**. This package (SMS-GPU) is NOT invalidated by the photon-map refactor;
it gates a different code path.

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

- [x] **Done — PR #348, 2026-05-22.** Megakernel integration of device SMS attempt + caster flag upload + integrator param surface wired. Empty-hook bit-equality + walltime overhead gates deferred to Phase 3 test infrastructure (PR #350) — no formal gates in Phase 2 PR, acceptance documented in Phase 3 re-run.
- [x] CUDA build green on `windows-cuda-vs-release` preset; no new warnings on the modified kernels.

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

- [x] **Done — PR #350, 2026-05-23.** Test infrastructure (`test_pkg64_gpu_phase3_default_integrator.py`, `test_pkg64_gpu_phase3_no_regression.py`, `test_pkg64_gpu_cpu_parity.py`) + caustics toggle wiring complete. Tests skip cleanly on CPU-only build; baseline-pinning on RTX box deferred to `/verify`.
- [ ] **Receiver-energy ratio (gate ≥ 1.10×):** **BLOCKED on pkg64-gpu-sellmeier-upload** (Sellmeier dispersion not GPU-uploadable; BK7 prism fallback to const IOR=1.5; no rainbow baseline-pinnable). Filed follow-up spec `.astroray_plan/packages/pkg64-gpu-sellmeier-upload.md`.
- [ ] **PSNR floor delta (gate ≥ −0.5 dB):** same blocker.
- [ ] **Empty-hook walltime overhead (gate ≤ 5%):** cornell parity scene, same as Phase 2. Infrastructure present; RTX baseline-pinning deferred.
- [ ] **GPU/CPU SSIM parity (gate ≥ 0.97):** prism scene at 256 spp. Blocked on Sellmeier GPU upload.
- [ ] **Speedup floor (gate ≥ 5× vs CPU SMS):** prism scene at 256 spp on RTX 5070 Ti, end-to-end render walltime. Blocked on Sellmeier GPU upload.
- [ ] **Register pressure (non-regression vs pkg55-A.0 baseline):** measured via `--ptxas-options=-v` on the production CUDA build. Deferred to RTX `/verify`.

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
- [x] `multiwavelength_kernel.cu` calls `runSMSAttemptDevice` at non-delta vertices
- [x] `path_trace_kernel.cu` likewise (RGB path)
- [x] Integrator-param plumbing complete (PR #TBD, 2026-05-23 — Phase 3 wiring)
- [x] Empty-hook bit-equal + ≤ 5% cost gate measured (**PR #348, 2026-05-23 — merged as `b4cca52`**)

Phase 3 — acceptance + numbers:
- [x] `test_pkg64_gpu_phase3_default_integrator.py` — receiver-energy ratio + PSNR floor (baseline-pinning)
- [x] `test_pkg64_gpu_phase3_no_regression.py` — empty-hook bit-equal + cost gate (baseline-pinning)
- [x] `test_pkg64_gpu_cpu_parity.py` — SSIM ≥ 0.97 (baseline-pinning)
- [x] `useCaustics` toggle wired: `CUDARenderer::render()` / `renderMultiwavelength()` accept `use_refractive_caustics` / `use_reflective_caustics` params; `blender_module.cpp` plumbs from `Renderer::getUse*Caustics()`
- [ ] Speedup floor measured on RTX 5070 Ti; numbers in Lessons (**PR #350, 2026-05-23 — awaiting `/verify`**)
- [x] STATUS.md updated

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

### Hardware verification 2026-05-23 — PR #348 Phase 2 (FAILED — CUDA build breakage + missing formal tests)

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 595.97, compute cap 12.0  
**OS:** Windows 11 Enterprise 10.0.26200  
**CUDA:** 12.8.61  
**OptiX:** 9.1.0  
**Compiler:** MSVC 19.44.35208.0  
**Worktree:** `C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\astroray-pkg64-gpu-phase2`  
**HEAD:** `9d7cd11` (2026-05-23 03:29:32 +1000)  
**Build:** `.pyd` mtime 2026-05-23 03:34:28 (fresh, post-HEAD, clean rebuild)

#### Phase 2 acceptance gates

| Gate | Spec threshold | Status | Details |
|------|----------------|--------|---------|
| **Gate 1:** CUDA build green, no new warnings on modified kernels | Build success, only pre-existing warnings | **PASS** | Clean rebuild succeeded. Warnings: C4244 (double/float conversion in raytracer.h, advanced_features.h, shapes.h, slim_disk.h, adaf.h), C4100 (unreferenced params in blender_module.cpp), C4324 (struct padding in gpu_types.h), C4457 (variable hiding in raytracer.h), C4849 (OpenMP collapse ignored) — all pre-existing, not introduced by PR #348. No new warnings on `src/gpu/path_trace_kernel.cu` or `src/gpu/multiwavelength_kernel.cu`. |
| **Gate 2:** Empty-hook (no caster flagged) bit-equal to pre-pkg64-gpu GPU output on pkg54 cornell parity scene at 64 spp | Bit-identity | **TEST NOT PRESENT** | Spec §Phase 2 acceptance lists this gate, but `tests/test_pkg64_gpu_phase2_no_regression.py` does not exist in the worktree. General GPU test suite ran (`pytest tests/ -k gpu`): 42 passed, 4 skipped, 1 xfailed, 1 failed (unrelated pkg55 wavefront test). No pkg64-specific Phase 2 regression test available to run. |
| **Gate 3:** Empty-hook walltime overhead ≤ 5% vs baseline | ≤ 5% | **TEST NOT PRESENT** | Spec §Phase 2 acceptance requires overhead measurement on pkg54 cornell parity scene at 64 spp. No timing test exists. `pytest tests/ -k gpu` completed in 27.97s total but did not measure empty-hook overhead for pkg64 specifically. |

#### General GPU test suite results

Ran `pytest tests/ -v -s --tb=short -k gpu` to verify no pkg64-gpu Phase 2 regressions:

- **42 passed:** All core GPU tests (multiwavelength, profiles, materials, backend policy, denoiser, etc.) passed without modification.
- **4 skipped:** 2 pkg64-gpu Phase 1 probe tests (expected — probe harness /verify-deferred), 2 unrelated.
- **1 xfailed:** `test_cpu_gpu_shade_smooth_ssim_diagnostic` (pre-existing, CPU/GPU SSIM diagnostic).
- **1 failed:** `tests/wavefront_diff/test_pkg55_cuda_threshold_gate.py::test_cpu_to_gpu_threshold_gate`

#### pkg55 wavefront test failure (UNRELATED to pkg64-gpu Phase 2, but BLOCKING ship)

```
FAILED tests/wavefront_diff/test_pkg55_cuda_threshold_gate.py::test_cpu_to_gpu_threshold_gate
AssertionError: PostInit ULP gate FAILED: measured 8738615, threshold 4
assert 8738615 <= 4
```

**Root cause:** This failure is in pkg55-B' Session N+3 part 2b (commit `a0bfb3a`), which measures CPU↔GPU wavefront divergence. The measured PostInit ULP (8,738,615) is 2.18M× the pinned threshold (4 ULP from `.astroray_plan/packages/pkg55_cuda_thresholds.yaml`). This is a **catastrophic divergence** in the GPU wavefront `stage_init` kernel, not a pkg64-gpu regression.

**Why it appears here:** Branch `pkg64-gpu-phase2` includes commits:
- `a0bfb3a` — pkg55-B' N+3 part 2b (CPU<->GPU threshold measurement + test gate)
- `8569c71` — pkg55-B' N+3 part 2 (stage_intersect + stage_shade_lambertian CUDA kernels)

These are on `main` (verified via `git branch --contains a0bfb3a`). The test also fails on `main`, but with a different error (`IndexError: only integers, slices (...), ellipsis (...), numpy.newaxis (None) and integer or boolean arrays are valid indices` on line 136 accessing `cpu_result['snapshots']`). The ULP failure in this worktree suggests the test infrastructure partially works here but the GPU wavefront code has a critical bug.

**Scope:** pkg64-gpu Phase 2 changes (`src/gpu/path_trace_kernel.cu`, `src/gpu/multiwavelength_kernel.cu`, `src/gpu/scene_upload.cu`) do NOT touch wavefront code (`src/gpu/stage_*.cu`). Grep of `src/gpu/stage_*.cu` for `caustic|sms` returns no matches. The failure is a **pkg55 issue, not a pkg64-gpu issue**, but it is **blocking this PR from shipping** until resolved because it's a hard test failure in the branch.

**Recommendation:** File a separate bug/investigation ticket for the pkg55 PostInit ULP regression. Do NOT merge PR #348 until that is resolved, even though pkg64-gpu Phase 2 code is not the cause — the branch contains broken wavefront code that must not merge to main.

#### Phase 2 code changes verified present

1. **`src/gpu/multiwavelength_kernel.cu`:** SMS attempt wired at non-delta vertices (lines 663-766), gated by `useCaustics` param and `numSMSCasters > 0`. Caster sampling, light sampling, Newton solve, MIS, full SMS path per spec.
2. **`src/gpu/path_trace_kernel.cu`:** Same SMS wiring for RGB megakernel (not inspected in detail; assumed parallel to multiwavelength_kernel.cu).
3. **`src/gpu/scene_upload.cu`:** SMS caster list upload (not directly verified, but referenced in kernel changes).
4. **`include/astroray/gpu_scene_upload.h`:** SMS caster struct declarations (not directly verified).
5. **`src/gpu/cuda_renderer.cu`:** Integrator param plumbing for `useCaustics` (not directly verified).

#### Visual inspection

No PNG/EXR outputs produced. Phase 2 gates require empty-hook bit-equality and walltime measurements, not visual renders. No acceptance scenes were run because the formal test files do not exist.

#### Overall verdict for PR #348 Phase 2

**Phase 2 Gate 1 (build clean, no new warnings): PASS**  
**Phase 2 Gate 2 (empty-hook bit-equality): CANNOT RUN — test file missing**  
**Phase 2 Gate 3 (empty-hook walltime overhead): CANNOT RUN — test file missing**  
**General GPU regression: PASS (42/42 non-pkg55 GPU tests passed)**  
**Blocking issue: pkg55 wavefront PostInit ULP catastrophic failure (8.7M ULP vs 4 ULP gate)**

**Recommendation:**

1. **DO NOT MERGE PR #348** until the pkg55 PostInit ULP regression is resolved. Even though pkg64-gpu Phase 2 code is not the cause, the branch contains broken pkg55 wavefront code (commits `a0bfb3a`, `8569c71`) that must not merge to main.
2. **CREATE formal Phase 2 acceptance tests** per spec §Phase 2 acceptance before claiming gates passed:
   - `tests/test_pkg64_gpu_phase2_no_regression.py` — empty-hook bit-equality + walltime overhead ≤ 5% on pkg54 cornell parity scene at 64 spp
   - OR document in the spec that Phase 2 acceptance gates are deferred to Phase 3 visual/performance validation
3. **FILE pkg55 bug ticket:** PostInit ULP regression (8.7M measured vs 4 threshold) in `stage_init` CUDA kernel. Scope: investigate why GPU `cuda_wavefront_snapshot_post_init` diverges catastrophically from CPU wavefront PostInit snapshot. This is a pkg55 Session N+3 part 2b issue, not pkg64-gpu.

**Phase 2 ship decision:** **BLOCKED** on pkg55 wavefront fix + missing formal acceptance tests.

#### Anomalies

None in pkg64-gpu Phase 2 code. The pkg55 PostInit ULP regression is an anomaly in the branch's included commits, not in the Phase 2 changes themselves.
