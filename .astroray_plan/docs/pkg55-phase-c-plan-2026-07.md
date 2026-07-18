# pkg55 Phase C — implementation plan (MIS audit + ReSTIR SoA + megakernel removal + 2× gate)

**Author:** planning pass, 2026-07-18. **Repo HEAD:** `c0f3130` (main).
**Package:** `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` (Phase C, spec §"Phase C — MIS/NEE parity + megakernel removal", lines 380–418).
**Status of prior phases:** Phase B' COMPLETE (PR #463) — wavefront produces images at megakernel parity + 1.50× perf + viewport-parity gate MET. Phase C is OPEN.

This is a **multi-session** plan. It is written to be executed one Session ("C1"…"C7") at a time, each with a measurable close gate and a rollback story, and it is **ordered so the two megakernel `.cu` files are deleted LAST**, only after every gate passes on the wavefront-only build. Precision over brevity is deliberate: this doc drives several implementation sessions.

---

## 0. What the wavefront already does vs. the megakernels (verified in code, not assumed)

The spec's Phase-C "deferred items" list (STATUS.md line 39, 71: *non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch*) is stale in one respect and correct in two. Verified against `c0f3130`:

| Capability | In wavefront today? | Evidence |
|---|---|---|
| Spectral path trace + NEE + power-heuristic MIS (light-sample side) | **YES** | `src/gpu/wavefront/stage_advance.cu:324-379` (NEE in `shadePathSlot`, MIS weight computed inline at `:344-347`); `src/gpu/gpu_nee.cuh:60-211` (shared `gpu_nee_sample`/`_occlude`/`_resolve`). |
| **Light-tree NEE selection** (pkg86-B) | **YES — already done** | Driver builds `treeView` and threads it through: `src/gpu/wavefront/gpu_wavefront_snapshot.cu:995-1001, 1127`; `gpu_nee_sample` descends the tree at `gpu_nee.cuh:79-90`. The "light-tree NEE branch" deferred item is effectively CLOSED for NEE selection. (The BSDF-ray-hits-emitter tree pdf is a different branch — see §4.) |
| Env-map miss / background / world-as-light | **YES** | `stage_advance.cu:179-194` via shared `gpu_env_miss_spectral` (`include/astroray/gpu_env_spectral.cuh`), `worldMaxBounces`-gated exactly like CPU. |
| Path regeneration, material-bucketed shade, dedicated shadow stage | **YES** | `stage_advance.cu` (`stageRegenKernel:978`, `stageIntersectQueuedKernel:632`, `stageShadeBucketedKernel:664`, `stageShadowKernel:560`); driver loop `gpu_wavefront_snapshot.cu:1105-1143`. |
| **TLAS / instancing** (pkg114) | **NO** | `intersectPathSlot` calls `gpu_bvh_hit(... motionVerts=nullptr)` (`stage_advance.cu:176-177`); NEE occlusion passes `tlas/instances/blas = nullptr` (`stage_advance.cu:367-369`, `:588-589`). The driver never builds `d_tlas/d_instances/d_blas` (`gpu_wavefront_snapshot.cu:988-997`). |
| **Geometry deformation motion blur** (pkg88-C.0) | **NO** | Every intersect/occlude passes `motionVerts=nullptr` and `time=0` (`stage_advance.cu:177, 369, 589`). No `ray.time` threading, no `d_motionVertices`. |
| **Non-visible-band profile override + luminance output + Rayleigh sky** (pkg54a / naive multiwavelength) | **NO** | Present only in the MW megakernel (`multiwavelength_kernel.cu:534-544, 701-715`). The wavefront always upsamples visible-band and always runs NEE. |
| **naive `multiwavelength_path_tracer` mode (`enableNEE=false`)** | **NO** | Wavefront `shadePathSlot` always does NEE; there is no `enableNEE` flag. |
| Spectral photon-map caustics (pkg113) | **NO** | MW-only: `multiwavelength_kernel.cu:846-863`. |
| Spectral SMS caustics (pkg64-gpu) | **NO** | MW-only: `multiwavelength_kernel.cu:578-673`. |
| GPU camera motion blur / shutter interpolation (pkg88-A) | **NO (and never was in the spectral path)** | RGB-megakernel-only: `path_trace_kernel.cu:688-719`. The MW kernel explicitly does NOT interpolate the camera (`multiwavelength_kernel.cu:807-810`). |
| GPU cryptomatte accumulation (pkg87b) | **NO** | RGB-megakernel-only: `path_trace_kernel.cu:583-609`. MW kernel has none; production cryptomatte is CPU-only. |
| ReSTIR reservoirs on GPU (pkg20-24) | **NO** | `restir_di` has no CUDA kernel at all (`plugins/integrators/restir_di.cpp:84-86` returns `gpuSupported=false`). |

**Load-bearing routing fact** (`module/blender_module.cpp:1556-1634`), because it decides what breaks on deletion:

- `wavefront_path_tracer` + `ASTRORAY_WAVEFRONT_CUDA_N3` build → `cuda_wavefront_render` (the wavefront).
- `path_tracer` → `renderMultiwavelength(… enableNEE=true)` → **MW megakernel** `multiwavelength_kernel.cu`.
- `multiwavelength_path_tracer` → `renderMultiwavelength(… enableNEE=false)` → **MW megakernel**.
- Any **other** GPU integrator name → `cudaRenderer->render()` → **RGB megakernel** `path_trace_kernel.cu`.

Consequence confirmed by the test sweep: the pkg88 GPU motion test, pkg113 GPU caustic test, and pkg64 GPU SMS test all `set_integrator("path_tracer")`, so **they exercise the MW megakernel, not the RGB kernel.** When Phase C repoints `path_tracer`/`multiwavelength_path_tracer`/`render()` at the wavefront and deletes both `.cu` files, *every GPU test* runs on the wavefront — so every feature a live GPU gate needs must be in the wavefront first. That is the spine of the risk list (§6).

---

## 1. Megakernel-only capability inventory + disposition

"Disposition" is one of: **EXTRACT** (shared code that must move to a surviving TU before deletion), **PORT** (must exist in the wavefront before deletion because a live gate needs it), **PORT-later / gate-behind-flag** (needed eventually but its gate is xfail or absent, so it does not block deletion), **DROP** (delete with justification — no live gate, superseded, or legacy).

### 1a. Shared infrastructure currently *housed inside* `multiwavelength_kernel.cu` — the hidden blocker

These are **not** megakernel behaviour; they are the spectral-tables layer the wavefront already depends on. Deleting the file link-breaks the wavefront. Must EXTRACT first.

| Symbol(s) | Defined | Consumed by (survives deletion) | Disposition |
|---|---|---|---|
| `uploadCmfTables()`, `g_cmfX/Y/Z`, `g_d65SPD`, `g_d65NormFactor` (pkg54b CMF/D65) | `multiwavelength_kernel.cu:160-221` | Wavefront driver `gpu_wavefront_snapshot.cu:1067`; `cuda_renderer.cu:723,913` | **EXTRACT** → `src/gpu/gpu_spectral_tables.cu` |
| `uploadJakobHanikaLut()`, `gpu_jhLookupCoeffs`, `gpu_jhEvalSpectrum`, `g_jhLut*` (pkg54c JH LUT) | `multiwavelength_kernel.cu:238-369` | Wavefront driver `:1068`; `cuda_renderer.cu:724,916` | **EXTRACT** |
| `gpu_spectrum_to_xyz()` (non-inline rdc export) + `spectrumToXYZ` inline + `xyzToLinearSRGB_dev` | `multiwavelength_kernel.cu:397-434` | Wavefront `stage_advance.cu:74-75,383,740,1011` (RR + accumulation) | **EXTRACT** (this is the single cross-TU XYZ entry the wavefront's Russian roulette + accumulation call) |
| `uploadProfileTable()`, `launchProfileLookup()`, `gpu_profile_reflectance()`, `g_profileTable` (pkg54a) | `multiwavelength_kernel.cu:50-112` | `cuda_renderer.cu:403,601,614` (profile upload + `_gpu_profile_lookup` binding, `tests/test_gpu_profile_lookup.py`) | **EXTRACT** (also the source the §1c non-visible-band port needs) |
| `gpu_sampleBandWavelengths`, `gpu_sampleD65`, `cmfSample`, `rayleighScale` | `multiwavelength_kernel.cu:118-143, 374-393, 439-442` | MW kernel + (band sampler) wavefront `stage_init` has its own copy | **EXTRACT** the shared ones; leave `rayleighScale` with the non-visible-band port (§1c) |

### 1b. `path_trace_kernel.cu` (RGB megakernel) capabilities

| Capability | Lines | Live GPU gate? | Disposition |
|---|---|---|---|
| RGB (non-spectral) path trace + `sampleDirectGPU` full BSDF-hits-emitter MIS (`bsdf_mis` block) | `:195-378, 639-772` | None (production `path_tracer` GPU = MW spectral; RGB `render()` is legacy per `blender_module.cpp:1572-1576`) | **DROP** — repoint `CUDARenderer::render()` at the wavefront (§3, C7) |
| `lightTreePickKernel` / `launchLightTreePick` (pkg86-B GPU parity probe) | `:869-900`; called `cuda_renderer.cu:485` | **YES** — `tests/test_pkg86_B_gpu_parity.py` (`debug_light_tree_pick_gpu`, ≥99.5% picks, pdf rel-err <1e-4, upload ≤10 ms) | **EXTRACT** → `src/gpu/light_tree_probe.cu` (it only needs `light_tree_device.cuh`; it is not path-trace code) |
| GPU camera motion blur / shutter slerp (pkg88-A): `GQuaternion`, `slerp`, `haltonBase2`, camera-basis interpolation | `:78-127, 688-719` | **None** — camera-MB GPU has no test (`test_motion_blur_phase_a.py` runs CPU only) | **PORT-later** to wavefront `stage_init` = pkg88 Phase D ("wavefront motion"); does not block deletion. Document as an explicitly-dropped-from-Phase-C GPU feature. |
| GPU cryptomatte accumulation (pkg87b): `crypto_accumulate_shade_point` | `:583-609, 730-737` | **None** — no GPU cryptomatte test exists; production cryptomatte is CPU (`test_cryptomatte_pass.py` renders CPU) | **DROP** — GPU cryptomatte accumulation is removed; CPU cryptomatte is the supported path. Record in STATUS as an intentional Phase-C drop. |
| RGB photon-map caustic gather / RGB SMS caustic | `:462-478, 480-567` | None (RGB path) — the *spectral* twins in the MW kernel carry the live pkg113/pkg64 gates | **DROP** (legacy RGB duplicates; spectral versions are the reference and are handled by §1c) |
| `initRNGKernel` / `launchInitRNG` (curandState init) | `:631-634, 840` | Megakernel infra only (wavefront uses PCG32 `WavefrontRNG`) | **DROP** with the megakernels |

### 1c. `multiwavelength_kernel.cu` (spectral megakernel) behaviours the wavefront lacks

| Capability | Lines | Live GPU gate that will land on the wavefront after deletion | Disposition |
|---|---|---|---|
| **Non-visible-band profile override + `useLuminanceOutput` + Rayleigh sky** (pkg54a NIR/UV) | `:534-544, 678-685, 701-715` | `tests/test_gpu_multiwavelength.py::test_nir_band_*` / `test_uv_band_*` (SSIM ≥ 0.97; ratio < 0.25) | **PORT** to the wavefront shade + accumulate stages |
| **`enableNEE=false` naive multiwavelength mode** | `multiwavelengthKernel` gated via `blender_module.cpp:1618` | pkg54 `multiwavelength_path_tracer` SSIM (spec Phase-C criterion) + `test_integrator_capabilities.py:53` | **PORT** (a flag in the wavefront driver + `shadePathSlot`) |
| **TLAS / instancing** (pkg114) via `gpu_tlas_hit` | `:519, 849` | pkg114 GPU instancing/refit tests (`test_tlas_refit.py`, inc-1/2/3 tests) — routing to be re-confirmed (see §6-R1) | **PORT** to `intersectPathSlot` + NEE occlusion (null-TLAS fallback is byte-identical, so it is a safe additive change) |
| **Geometry deformation motion blur** (pkg88-C.0): `motionVerts`, `ray.time`, `gpu_mw_haltonBase2` | `:811, 849, 519` | `test_pkg88_c0_deformation.py::test_motion_blur_gpu_streak_and_parity` (streak > 2×, energy ratio 0.93–1.08) | **PORT** to the wavefront (thread `ray.time` + `d_motionVertices` through the SoA) |
| **Spectral photon-map caustics** (pkg113) | `:846-863` | `test_gpu_caustic_parity.py::test_gpu_glass_sphere_caustic_parity` (peak > 0.20, ROI ratio 0.5–2.0, **SSIM ≥ 0.80 — LIVE**) | **PORT** (post-shade primary-hit gather stage) |
| **Spectral SMS caustics** (pkg64-gpu) | `:578-673` | `test_pkg64_gpu_cpu_parity.py` is **`xfail(strict=False)`** | **PORT-later / gate-behind-flag** — xfail means it does not block deletion; port as a follow-up |

---

## 2. The extraction is the real unlock (why deletion is not `rm`)

The naïve reading of the spec ("delete two files, flip two dispatch branches") link-breaks the build the moment `multiwavelength_kernel.cu` is removed, because the wavefront driver and `cuda_renderer.cu` call `uploadCmfTables` / `uploadJakobHanikaLut` / `gpu_spectrum_to_xyz` / `uploadProfileTable` / `launchProfileLookup` that live inside it (§1a), and `test_pkg86_B_gpu_parity.py` calls `launchLightTreePick` that lives inside `path_trace_kernel.cu` (§1b). **Session C1 is therefore a pure, behaviour-preserving refactor that turns the eventual deletion into a clean unlink.** Every later session builds on a codebase where the shared spectral layer already has a home that survives.

---

## 3. Staged increment plan

Each session = one PR, one close gate, one rollback story. Ordering guarantees the megakernel stays the production/reference path until C7.

### Session C1 — Extract shared spectral-tables + light-tree probe (pure refactor, zero behaviour change)
- **Deliverable:** new `src/gpu/gpu_spectral_tables.{cu,h}` holding the §1a symbols (CMF/D65/JH/profile tables + `gpu_spectrum_to_xyz`); new `src/gpu/light_tree_probe.cu` holding `lightTreePickKernel`/`launchLightTreePick`. Both megakernels and the wavefront `#include` the new header; the `.cu` symbols are defined once. CMake wires the two new TUs into `astroray_cuda`.
- **Gate:** full RTX suite green with **byte-identical renders** for all three paths (RGB `render()`, MW `renderMultiwavelength`, wavefront `cuda_wavefront_render`) — the refactor moves code, changes no codegen. `test_pkg86_B_gpu_parity.py` + `test_gpu_profile_lookup.py` still green (they now hit the extracted TUs). `cpp-abi-guard` pass (constant-memory symbols crossing TUs).
- **Rollback:** revert the file move; nothing else touched.

### Session C2 — MIS audit (instrumentation + per-stage parity gate)
- **Deliverable:** add `path_mis_pdf` (BSDF pdf) and `path_light_pdf` (selection×solid-angle pdf, incl. tree pdf) to the wavefront SoA + `WavefrontSnapshot`; a new `PostNEE_MIS` per-stage diff gate (CPU-wavefront ↔ CPU reference, exact; CPU ↔ GPU, ULP/p99.9) proving the wavefront's shade-time MIS weight equals the CPU `pathTraceSpectral` / MW-megakernel weight. See §4 for the design + Cycles citations.
- **Gate:** new MIS per-stage gate passes; all existing final-image + perf gates unchanged (the field is instrumentation — no transport change).
- **Rollback:** additive SoA field + additive test; drop both.

### Session C3 — Naive-multiwavelength mode + non-visible bands (closes the pkg54/54a gates on the wavefront)
- **Deliverable:** thread `enableNEE`, `useLuminanceOutput`, `lambdaMin/Max`, and the non-visible-band profile override (`gpu_profile_reflectance` from the C1-extracted TU) + Rayleigh-sky miss fallback through `cuda_wavefront_render` → `shadePathSlot` / `intersectPathSlot` / accumulate, mirroring `multiwavelength_kernel.cu:534-544, 678-715`. Route `multiwavelength_path_tracer` GPU at the wavefront (still behind the megakernel default).
- **Gate:** `test_gpu_multiwavelength.py` visible (SSIM ≥ 0.998), NIR/UV-with-profiles (SSIM ≥ 0.97, ratio < 0.25), NIR-no-profile-fallback (SSIM ≥ 0.97) all pass **on the wavefront**; visible-band no-regression ≤ 2%.
- **Rollback:** flag-gated; megakernel remains the default dispatch.

### Session C4 — TLAS/instancing + geometry motion in the wavefront
- **Deliverable:** build `d_tlas/d_instances/d_blas` in the wavefront driver (reuse `buildSceneArrays` output already produced at `gpu_wavefront_snapshot.cu:988`); switch `intersectPathSlot` + `gpu_nee_occlude` from `gpu_bvh_hit` to `gpu_tlas_hit`/`gpu_tlas_occluded` (null-TLAS path is byte-identical — proven by pkg114 inc-1 identity test); thread `ray.time` + `d_motionVertices` through the SoA (add `path_time` field) and `gpu_mw_haltonBase2` into `initPathSlot`.
- **Gate:** pkg114 GPU instancing/refit tests + `test_pkg88_c0_deformation.py::test_motion_blur_gpu_streak_and_parity` pass on the wavefront; static-scene renders byte-unchanged (null TLAS / `time=0`).
- **Rollback:** null-TLAS + `motionVerts=nullptr` fallback restores exact current behaviour.

### Session C5 — Spectral photon-map caustics in the wavefront (keeps pkg113 live gate)
- **Deliverable:** a post-shade primary-hit photon-gather stage mirroring `multiwavelength_kernel.cu:846-863` (`photonGridGatherKnn` at the first non-emissive hit, add `albedo·E·photonScale` in XYZ); optionally SMS (pkg64) behind a flag (xfail, non-blocking).
- **Gate:** `test_gpu_caustic_parity.py::test_gpu_glass_sphere_caustic_parity` (SSIM ≥ 0.80) passes on the wavefront; pkg64 stays xfail.
- **Rollback:** gated by `hasPhotonGrid`; off = current behaviour.

### Session C6 — ReSTIR reservoir SoA + wavefront reuse stages (closes pkg24 on GPU)
- **Deliverable:** flat reservoir SoA (double-buffered) + temporal/spatial reuse as wavefront stages + `restir_di` GPU dispatch. See §5 for the SoA layout and the GRIS anchor. This is the largest session; may split C6a (SoA + initial RIS + resolve) / C6b (temporal + spatial reuse).
- **Gate:** `test_restir_validation.py::TestTemporalVariance::test_temporal_reduces_variance` passes with `restir-di` on the **GPU wavefront** (stddev_temporal < stddev_no_reuse); ReSTIR-DI bias tests (10% thresholds) hold.
- **Rollback:** `restir_di` keeps its CPU path (`capabilities().gpuSupported=false`) until the gate is green; the GPU dispatch is opt-in until then.

### Session C7 — 2× end-to-end gate, then delete the megakernels (LAST)
- **Deliverable (in order):** (1) confirm every gate above is green on a wavefront-only run; (2) add/turn on the **≥ 2× end-to-end** gate (Disney contact sheet, 7 materials, **1024 spp**, wavefront vs the pinned Phase-A megakernel baseline `benchmarks/wavefront/baseline.json`), extending `tests/wavefront_diff/test_pkg55_perf_gate.py`; (3) repoint `CUDARenderer::render()` and `renderMultiwavelength()` (and the `path_tracer`/`multiwavelength_path_tracer` dispatch in `blender_module.cpp:1597-1634`) at the wavefront; (4) **delete `src/gpu/path_trace_kernel.cu` + `src/gpu/multiwavelength_kernel.cu`**, remove their launch decls from `cuda_renderer.cu:38-90` and `src/gpu/gpu_renderer.h`, drop the megakernel dispatch branches; (5) repo-wide stale-call-site sweep per CLAUDE.md (grep every deleted symbol: `launchPathTraceKernel`, `launchMultiwavelengthKernel`, `launchInitRNG`, `pathTraceKernel`, `multiwavelengthKernel`, `tracePathGPU`, `sampleDirectGPU`, `tracePathMW`, `sampleDirectSpectralMW` — the last two are `gpu_nee.cuh`-recomposed and must still resolve).
- **Gate:** full RTX suite green (all pkg54/54a/54b + pkg24 + pkg113 + pkg88 + pkg114 gates now on wavefront); **≥ 2× gate passes**; no megakernel symbol resolves anywhere; `STATUS.md` + spec flipped to pkg55 COMPLETE.
- **Rollback:** the deletion is one commit — `git revert` restores both kernels and the dispatch. Because C1–C6 already made the wavefront serve every gate, the revert is a safety net, not an expected step.

---

## 4. MIS audit design

**Finding:** the wavefront is *already* MIS-correct against its reference, but the correctness is unaudited and its structure differs from the spec's sketch. The audit adds instrumentation + a gate; it does not re-architect.

**What the reference does.** Both the CPU `pathTraceSpectral` (mirrored at `gpu_nee.cuh:24-25, 199-210`, citing `raytracer.h:2405-2424`) and the MW megakernel `tracePathMW` use a **one-sided MIS**: the NEE light-sample contribution is weighted by the power heuristic `wt = lightPdf² / (lightPdf² + bsdfPdf²)` (`gpu_nee.cuh:27, 208`), and the emitted term at a surface is added **only** for `bounce==0 || wasSpecular` (`multiwavelength_kernel.cu:552-557`; wavefront `stage_advance.cu:200-210`). The diffuse-bounce BSDF-ray-hits-emitter term is *dropped*, not MIS-weighted — so there is no double count and no missing energy relative to the reference. The RGB `path_trace_kernel.cu::sampleDirectGPU` (`:348-375`) additionally carries a full `bsdf_mis` branch that *does* weight BSDF-sampled emitter hits; **that branch is RGB-only and is NOT part of the spectral reference**, so the wavefront correctly omits it.

**Where the wavefront computes MIS today.** In `shadePathSlot` at shade time: `bsdfPdf = gpu_material_pdf(...)` then `wt = a2/(a2+b2+1e-8)` folded into the parked contribution (`stage_advance.cu:341-347`). This differs from the spec's Phase-C decision #1 sketch (park `path_mis_pdf`, weight in `stage_shadow`). Both are valid; the shade-time form is already implemented and is the one to audit.

**`path_mis_pdf` SoA placement.** Add to `GPUWavefrontState` (`include/astroray/gpu_wavefront_state.h:64-114`), next to `throughput_*`:
- `float* path_light_pdf` — the NEE selection×solid-angle pdf `s.lightPdf` (includes the light-tree traversal pdf from `gpu_nee_sample:85` when the tree is resident).
- `float* path_mis_pdf` — the BSDF pdf `gpu_material_pdf(mat, rec, wo, s.wi)` at the NEE direction.

These are written in `shadePathSlot` where both are already computed (`stage_advance.cu:341, 344`) and read by the new `PostNEE_MIS` snapshot stage. They are **instrumentation for the gate**, not a transport change — the weight keeps being applied at shade. (If a later session wants the spec's shadow-stage MIS form, these two fields are exactly the payload to park; the audit leaves that door open without walking through it.)

**Cycles reference to mirror (CLAUDE.md §6).** Cite, do not re-derive:
- `intern/cycles/kernel/integrator/shade_surface.h` — `integrate_surface_direct_light()`: the canonical ordering "sample light → `bsdf_eval` at the shading point → compute MIS weight → queue the shadow ray" that the wavefront's shade-then-shadow split mirrors (already noted at `stage_advance.cu:104-105, 333-337`).
- `intern/cycles/kernel/light/sample.h` — `light_sample_mis_weight` / `power_heuristic`: the power-heuristic form `a²/(a²+b²)` the audit checks `gpu_mw_powerHeuristic` against.
- `intern/cycles/kernel/integrator/shade_light.h` + `intersect_closest.h` — `light_sample_from_intersection()` + its MIS weight: this is the *BSDF-ray-hits-light* MIS the reference deliberately omits; cite it to document **why** the spectral path uses the emissive gate instead (the audit's written justification for not adding a `bsdf_mis` branch).
- Veach 1997 (power heuristic), already cited in `gpu_nee.cuh:208` and `path_trace_kernel.cu:132-136`.

**Audit gate.** Extend the per-stage harness (`tests/wavefront_diff/measure_thresholds.py`, gate `test_pkg55_cuda_threshold_gate.py`) with a `PostNEE_MIS` stage comparing `(path_light_pdf, path_mis_pdf, resulting wt)`: exact (0.0) CPU-wavefront ↔ CPU reference; ULP/p99.9-bounded CPU ↔ GPU (same two-tier structure as PostShade, thresholds pinned in `pkg55_cuda_thresholds.yaml` per the GATE-THRESHOLDS-PINNED rule, spec §4.2). Deliverable of the audit: a written statement, backed by the gate, that the wavefront's MIS equals the reference to within the pinned tolerance and that the omitted RGB `bsdf_mis` branch is intentional.

---

## 5. ReSTIR-to-wavefront design sketch

**Foundation + licensing (per `.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 8).** Cite **GRIS — Lin, Kettunen, Bitterli, Pantaleoni, Yuksel, Wyman, "Generalized Resampled Importance Sampling," ACM ToG 41(4), SIGGRAPH 2022, DOI 10.1145/3528223.3530158** as the canonical reference for moving ReSTIR reservoirs into GPU SoA stages. **Hard licensing rule:** NVIDIA RTXDI is proprietary (verified from `RTXDI LICENSE.txt §4(e)`) and **DISQUALIFIED** — do not read or mirror it. Use the paper plus `github.com/DQLin/ReSTIR_PT` (**license must be verified before any code is mirrored** — treat as blocked until confirmed Apache/BSD/MIT/MPL per CLAUDE.md §6) or reimplement from the paper + our own CPU code. Save the license verification result into this docs folder before Session C6 writes reservoir code.

**Scope for Phase C.** The current CPU integrator is **classic Bitterli-2020 ReSTIR DI**, not full GRIS path-space resampling (`plugins/integrators/restir_di.cpp:8-31`). Phase C's job (spec Phase-C decision #2) is to move *that* DI reservoir into wavefront SoA and pass the existing pkg24 temporal-variance gate — GRIS is cited as the **roadmap/justification** for the resampling generalization and is the reference a *later* package (partitioned-SMS+ReSTIR caustics, research finding 2) would build on. Do not expand to path-space GRIS in Phase C.

**One-generator rule (spec decision #9).** The CPU `Reservoir<T>::update/merge/finalizeWeight` (`include/astroray/restir/reservoir.h:41-69`) uses `std::mt19937` + `std::uniform_real_distribution` and is not device-callable. Rather than transcribe it (the exact mistake decision #9 forbids), refactor the reservoir core into a **shared `__host__ __device__` template over the RNG type**, exactly like the template-RNG arc that unified the material samplers (`stage_advance.cu:57-66`, `gpu_rng_uniform` ADL dispatch). Then the CPU `restir_di` and the GPU reuse stages call the *same* `update`/`merge`/`finalizeWeight` arithmetic — one generator, and the CPU trip-wire becomes the GPU oracle.

**Reservoir SoA layout** (flat, per-pixel, **double-buffered** `current`/`previous` to mirror `FrameState` and its race-free reuse policy, `frame_state.h:138-165`). Mirroring `Reservoir<ReSTIRCandidate>` (`reservoir.h:26-30`) + `ReSTIRCandidate` (`light_sample.h:25-31`) + `PixelHistory` (`frame_state.h:35-39`), all as component arrays of length `numPixels`:

```
// selected candidate y (ReSTIRCandidate)
float* res_y_pos_x/_y/_z          // candidate.position
float* res_y_normal_x/_y/_z       // candidate.normal
float* res_y_emission_x/_y/_z     // candidate.emission (RGB)
float* res_y_pdf                  // candidate.pdf
float* res_y_distance             // candidate.distance
// reservoir bookkeeping
float* res_w_sum                  // Reservoir.w_sum
int*   res_M                      // Reservoir.M
float* res_W                      // Reservoir.W (final RIS weight)
// PixelHistory (temporal-validity gate)
float* meta_normal_x/_y/_z        // PixelHistory.normal
float* meta_depth                 // PixelHistory.depth
int*   meta_valid                 // PixelHistory.valid (0/1)
```

Allocated once per resolution in the persistent `WfContext` (`gpu_wavefront_snapshot.cu:987`, `wfEnsure` grow-only), two copies, swapped per frame (device-side pointer swap = `FrameState::advanceFrame`, `frame_state.h:160`).

**Reuse as wavefront stages** (spec decision #2: between `STAGE_SHADE` and the next `STAGE_INTERSECT`; here they run at the **primary/bounce-0** shade because ReSTIR-DI reuses only at the primary shading point — `restir_di.cpp:215`):
1. **Initial RIS stage** — per pixel draw `numCandidates` light samples, `res.update(cand, pHat/pdf)` (mirror `restir_di.cpp:199-206`), M-cap at `20×M` (`:209-210`), write `current`.
2. **Temporal reuse stage** — read `previous[pixel]`, gate with `isTemporallyValid` (`frame_state.h:86-109`), `res.merge(prev, pHatPrev)` (`restir_di.cpp:222-231`). Reads `previous` only → race-free, matching the CPU policy (`restir_di.cpp:20-31`).
3. **Spatial reuse stage** — `selectSpatialNeighbors` (`frame_state.h:121-136`) over `previous`, merge each valid neighbour (`restir_di.cpp:234-252`). GRIS offline recipe (research finding 8) for a future unbiased mode: temporal OFF, 32 candidates/px, 3 spatial rounds, 6 neighbours, 10 px radius.
4. **Resolve stage** — `finalizeWeight` (`reservoir.h:64`), shadow-ray to `res_y_pos`, on unoccluded add `throughput · f_spec · L_spec · res.W` (mirror `restir_di.cpp:257-313`), fold into the existing wavefront `color` SoA. The shadow ray reuses `gpu_nee_occlude`/`stageShadowKernel` machinery.

**Explicit out-of-scope for the GPU port (document, don't port):** the CPU `restir_di` GR-object delegation (`restir_di.cpp:151-179`) and CPU cryptomatte accumulation (`:291-310, 330-348`) — GR is a CPU integrator-surface feature per Phase B' non-goals, and cryptomatte is CPU-only (see §1b). The GPU ReSTIR path serves standard geometry + area/env lights.

---

## 6. Risk list — what could block megakernel deletion (verified in code)

- **R1 — pkg114 TLAS/instancing not in the wavefront (verified NO).** `intersectPathSlot` uses `gpu_bvh_hit`; the driver builds no `d_tlas` (§0). If the pkg114 GPU tests route through `render()`/`renderMultiwavelength` (they call `r.render()`; integrator name TBD), deleting the megakernels makes them run on a wavefront with no instancing → failures. **Mitigation:** Session C4 ports TLAS (null-fallback is byte-identical). **Action for C1/C4:** grep `test_tlas_refit.py` + pkg114 inc tests for `set_integrator(...)` to confirm which kernel they hit today and thus whether they are load-bearing on deletion.
- **R2 — pkg88 geometry motion not in the wavefront (verified NO).** `test_pkg88_c0_deformation.py::test_motion_blur_gpu_streak_and_parity` uses `path_tracer`+GPU → MW kernel → will land on the wavefront. **Mitigation:** Session C4.
- **R3 — pkg113 photon caustics not in the wavefront (verified NO), LIVE gate.** `test_gpu_caustic_parity.py` SSIM ≥ 0.80 is not xfail. **Mitigation:** Session C5. (pkg64 SMS is xfail → not blocking, PORT-later.)
- **R4 — pkg54a non-visible bands + naive-MW mode not in the wavefront (verified NO), LIVE gates.** The Phase-C criterion "all pkg54/54a/54b gates pass with wavefront" **requires** the wavefront to support NIR/UV profile override + luminance output + `enableNEE=false`. This is the "deferred non-visible-band profile override" item, and it is on the **critical path**, not optional. **Mitigation:** Session C3.
- **R5 — shared spectral tables + light-tree probe live inside the deleted files (verified).** `uploadCmfTables`/`uploadJakobHanikaLut`/`gpu_spectrum_to_xyz`/`uploadProfileTable`/`launchProfileLookup` (in `multiwavelength_kernel.cu`) and `launchLightTreePick` (in `path_trace_kernel.cu`) are called by surviving code (§1a, §1b). Deleting the files link-breaks the build + `test_pkg86_B_gpu_parity.py`. **Mitigation:** Session C1 (must be first).
- **R6 — `CUDARenderer::render()` RGB path has no wavefront equivalent.** The RGB `render()` entry (`cuda_renderer.cu:861`) is the GPU path for non-spectral integrator names and the direct `render()` binding. Deleting `path_trace_kernel.cu` removes it. **Mitigation:** C7 repoints `render()` at the wavefront (visible-band spectral → RGB). **Risk:** any test asserting *exact* RGB-megakernel pixels (not SSIM) would shift to the spectral pipeline; C7's sweep must catch these. Camera-MB GPU (pkg88-A) and GPU cryptomatte (pkg87b) are DROP (no gate) — confirm no hidden caller before C7.
- **R7 — ReSTIR device reservoir transcription risk.** The CPU `Reservoir<T>` is not device-callable (`std::mt19937`). A hand-transcribed device copy would violate decision #9 and re-open whack-a-mole. **Mitigation:** shared `__host__ __device__` template (§5); CPU trip-wire as GPU oracle.
- **R8 — DQLin/ReSTIR_PT license unverified.** Blocks mirroring any GRIS reference code. **Mitigation:** verify license before C6 writes code; the CPU ReSTIR-DI code is the primary generator regardless, so this only gates *reference* borrowing, not the port.
- **R9 — 2× gate is scene/thermal-sensitive.** Phase B' showed the 1.5× ratio straddled the threshold under thermal drift; the ratio is the robust metric, absolute times drift (STATUS line 55). The ≥2× target is vs the **Phase-A megakernel baseline at 1024 spp**, a bigger ask than the 1.5× @512 gate. **Mitigation:** measure ratio on a cool GPU (owner-confirmed temps), keep the hard floor + xfail-strict=False pattern already used in `test_pkg55_perf_gate.py` until a clean cool run clears 2×.
- **R10 — MW `worldMaxBounces` env-gate parity.** Already handled (both paths gate env accumulation identically — `stage_advance.cu:182`, `multiwavelength_kernel.cu:531`, regression-gated by `test_pkg55_megakernel_env_open_scene.py`); listed so C7's deletion of that megakernel-only regression test is a conscious choice (retarget it at the wavefront or retire it).

---

## 7. Recommendation for the FIRST session

**Do Session C1 first (extract shared spectral-tables + light-tree probe).** Rationale:
- It is the one prerequisite that turns "delete two files" from a link-break into a clean unlink (R5) — nothing else in Phase C can safely reach the deletion without it.
- It is a **pure, zero-behaviour-change refactor**: highest safety, byte-identical renders, trivial rollback, and it exercises the `cpp-abi-guard` discipline for the constant-memory symbols before any risky work.
- It unblocks C2–C7 in parallel-friendly order (C3/C4/C5 become independent ports once the shared layer has a home).

**Pair it with the MIS audit (C2) in the same arc if session budget allows** — C2 is additive instrumentation with no transport change, it directly answers the spec's named "MIS audit via `path_mis_pdf` SoA field," and it produces the written parity statement early, de-risking the C3–C5 ports that all lean on the NEE/MIS path. If budget is tight, ship C1 alone (it is the true blocker) and take C2 next.

Concretely, the first PR should: create `src/gpu/gpu_spectral_tables.{cu,h}` + `src/gpu/light_tree_probe.cu`, move the §1a/§1b-probe symbols, update the three `#include` sites + CMake, and prove byte-identical output on the RGB, MW, and wavefront paths plus green `test_pkg86_B_gpu_parity.py` / `test_gpu_profile_lookup.py`.
