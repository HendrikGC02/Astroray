# pkg55 — Wavefront SoA GPU Refactor

**Pillar:** 5  
**Track:** A  
**Status:** open (research signed off — see [wavefront-gpu-research.md](../docs/wavefront-gpu-research.md))  
**Estimated effort:** 10–11 weeks total across three phases (Phase A: 3–4 w, Phase B: 4 w, Phase C: 3 w)  
**Depends on:** pkg54 (megakernel reference, done), pkg54a (spectral-profile dispatch, done), pkg54b (CIE 1964 CMF parity, done). pkg54c (Jakob-Hanika GPU upsampling) may overlap Phase B — see §Research/Risk 6.

---

## Goal

**Before:** Astroray's GPU path tracer is a megakernel: one monolithic CUDA kernel handles BVH traversal, material evaluation, NEE, and radiance accumulation for each path in a single launch. Warp divergence from mixed materials and high register pressure cap practical GPU occupancy. The megakernel's performance degrades proportionally to material diversity.

**After:** A wavefront GPU pipeline where paths advance through a sequence of typed stages (intersect, shade, shadow, miss, terminate). Paths are sorted by material type before the shade stage, keeping warps fully coherent during BSDF evaluation. Per-path state lives in SoA global-memory arrays between stages, enabling coalesced reads and writes. The megakernel is removed. All four integrators (`path_tracer`, `multiwavelength_path_tracer`, `restir_di`, `neural-cache`) use the wavefront pipeline.

**Performance target:** ≥ 2× frame-time improvement over the removed megakernel on a mixed-material scene (≥ 4 distinct material types, 1024 SPP). This is consistent with Cycles X's measured 2.2× speedup on the Koro scene (Blender 3.0 release notes) and with Laine et al. 2013 (HPG, DOI [10.1145/2492045.2492060](https://dl.acm.org/doi/10.1145/2492045.2492060)) who reported 2× or better speedup in material-diverse scenes.

---

## Context

pkg54/54a/54b landed a CUDA megakernel mirror of `multiwavelength_path_tracer` and achieved SSIM parity ≥ 0.985 vs CPU at 64 spp. That work was explicitly scoped as "megakernel first; wavefront SoA is pkg55." The megakernel is now the production path and defines the acceptance baseline.

The research note ([wavefront-gpu-research.md](../docs/wavefront-gpu-research.md)) documents:
- Why wavefront solves the warp-divergence problem (Laine 2013 §3–§5).
- The exact SoA field mapping from `gpu_types.h` (GHitRecord, GBSDFSample, GSampledSpectrum, GSampledWavelengths) to per-path arrays.
- The 6-stage queue design and how it maps to Astroray's integrators.
- Sort-by-material dispatch for the 7 GMaterialType values, with OptiX SBT trade-off documented.
- Spectral state sizing: 48 bytes/ray (lambda + pdf + throughput), 14.4 MB total for 65 536 concurrent paths.
- Three-phase migration plan keeping the megakernel live through Phase B.

---

## Reference

- Research note: [.astroray_plan/docs/wavefront-gpu-research.md](.astroray_plan/docs/wavefront-gpu-research.md)
- Cycles wavefront kernel (Apache-2.0): [blender/cycles @ c9227ff](https://github.com/blender/cycles/tree/c9227ff33cc79f859d77e493e9a0969955f721be) — `src/kernel/integrator/state.h`, `state_template.h`, `intersect_closest.h`, `shade_surface.h`, `init_from_camera.h`, `src/device/cuda/queue.cpp`
- PBRT-v4 wavefront (Apache-2.0): [mmp/pbrt-v4 @ eef3a6e](https://github.com/mmp/pbrt-v4/tree/eef3a6ef634a7d83dc98458334dfdfbbe8906d53) — `src/pbrt/wavefront/integrator.cpp`, `workitems.soa`, `workqueue.h`
- Laine, Karras, Aila 2013: "Megakernels Considered Harmful: Wavefront Path Tracing on GPUs." HPG 2013. DOI: [10.1145/2492045.2492060](https://dl.acm.org/doi/10.1145/2492045.2492060). PDF: [NVIDIA Research](https://research.nvidia.com/publication/2013-07_megakernels-considered-harmful-wavefront-path-tracing-gpus).
- Astroray GPU types: `include/astroray/gpu_types.h` — GHitRecord, GBSDFSample, GSampledSpectrum, GSampledWavelengths, GMaterial, GMaterialType.
- Megakernel baseline: `src/gpu/path_trace_kernel.cu`, `src/gpu/multiwavelength_kernel.cu`.

---

## Specification

### Phase A — SoA state infrastructure + intersect queue

**Estimated effort:** 3–4 weeks

**Goal:** Allocate SoA path state buffers and validate the first two stages (init + intersect) against the megakernel's BVH output. No pixel output from wavefront yet — purely a parity check on hit records.

#### Files to create

| File | Purpose |
|---|---|
| `include/astroray/integrator_state_soa.h` | `IntegratorStateSoA` struct: all per-path SoA device pointer arrays + concurrent-path count. |
| `src/gpu/wavefront/stage_init.cu` | Init stage kernel: samples camera ray + `GSampledWavelengths`, writes ray SoA. |
| `src/gpu/wavefront/stage_intersect.cu` | Intersect stage kernel: reads ray SoA, runs `gpu_bvh_hit`, writes hit record SoA + `path_sort_key`. |
| `src/gpu/wavefront/queue_dispatch.cpp` | Host-side dispatch loop: checks `num_queued[]`, launches stage kernels. |
| `tests/test_wavefront_intersect_parity.py` | Validates that `hit_t[i]` / `hit_mat[i]` from the wavefront intersect stage match the megakernel's BVH call bit-for-bit on the pkg54 parity scene. |

#### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add `src/gpu/wavefront/` source directory and wavefront lib target. |
| `src/gpu/gpu_renderer.h` | Declare `IntegratorStateSoA` allocation/free helpers. |
| `module/blender_module.cpp` | Allocate SoA buffers at `Renderer` startup when CUDA is active. |

#### Key design decisions (Phase A)

1. **Concurrent path count:** `max(max_num_threads, 65536) * 16`, configurable via `ASTRORAY_CONCURRENT_PATHS_FACTOR` env var (matching Cycles `CYCLES_CONCURRENT_STATES_FACTOR`).
2. **float4 padding for vec3 arrays:** `ray_origin`, `ray_dir`, `hit_normal` stored as float4 with `w=0` to guarantee 16-byte alignment and coalesced access. Do not use 3-float (12-byte) pitched arrays.
3. **Megakernel stays active:** The wavefront pipeline in Phase A produces no framebuffer output. The megakernel continues to run unchanged. The intersect parity test is a debug-mode assertion, not a render path.
4. **RNG keying:** The init kernel keys RNG by `(path_pixel, path_sample, 0)` — not by thread ID — to preserve deterministic output. Match Cycles `rng_pixel` + `rng_offset` convention.

#### Phase A acceptance criteria

- [ ] `IntegratorStateSoA` allocates without error on the RTX 5070 Ti for `max_concurrent_paths = 65536 * 16`.
- [ ] Intersect parity test passes: for 512 camera rays on the pkg54 parity scene, `hit_t`, `hit_prim`, `hit_mat` from the wavefront intersect stage match the megakernel's BVH results exactly (bit-identical floats).
- [ ] Megakernel render output unchanged: pkg54b SSIM ≥ 0.985 still passes.
- [ ] CUDA build green; no new compiler warnings.

---

### Phase B — Shade queue + material dispatch + wavefront pixel output

**Estimated effort:** 4 weeks

**Goal:** Wire all six stages. The wavefront integrator produces its own framebuffer output and is exposed as `wavefront_path_tracer`. Compare SSIM against the megakernel and against the CPU `path_tracer`.

#### Files to create

| File | Purpose |
|---|---|
| `src/gpu/wavefront/stage_shade_lambertian.cu` | Shade kernel for `GMAT_LAMBERTIAN`. |
| `src/gpu/wavefront/stage_shade_metal.cu` | Shade kernel for `GMAT_METAL`. |
| `src/gpu/wavefront/stage_shade_dielectric.cu` | Shade kernel for `GMAT_DIELECTRIC`. |
| `src/gpu/wavefront/stage_shade_disney.cu` | Shade kernel for `GMAT_DISNEY`. |
| `src/gpu/wavefront/stage_shade_thin_glass.cu` | Shade kernel for `GMAT_THIN_GLASS`. |
| `src/gpu/wavefront/stage_shade_diffuse_light.cu` | Shade kernel for `GMAT_DIFFUSE_LIGHT` (emission accumulation). |
| `src/gpu/wavefront/stage_shade_closure_graph.cu` | Shade kernel for `GMAT_CLOSURE_GRAPH`. |
| `src/gpu/wavefront/stage_shadow.cu` | Shadow ray any-hit BVH + NEE radiance accumulation. |
| `src/gpu/wavefront/stage_miss.cu` | Env map miss + accumulation. |
| `src/gpu/wavefront/stage_terminate.cu` | Russian roulette + final pixel write. |
| `src/gpu/wavefront/material_sort.cu` | CUB DeviceRadixSort on `path_sort_key` after intersect. |
| `plugins/integrators/wavefront_path_tracer.cpp` | New integrator plugin dispatching the wavefront pipeline. |
| `tests/test_wavefront_parity.py` | Wavefront vs CPU `path_tracer` SSIM test on pkg54 parity scene (NIR + visible). |

#### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Wire `renderGPU()` to the wavefront pipeline in addition to the megakernel. Controlled by a new `use_wavefront` param (default false until Phase C). |
| `module/blender_module.cpp` | Register `wavefront_path_tracer` in the integrator dropdown. |
| `.astroray_plan/docs/STATUS.md` | Record Phase B completion. |

#### Key design decisions (Phase B)

1. **One shade kernel per material type.** Dispatch after sort-by-material, not a switch inside a single kernel. Each kernel is launched for its non-empty bucket only (`num_queued[GMAT_*] > 0` guard).
2. **Double-buffered ray queues.** `QUEUE_INTERSECT_A` (init output) ↔ `QUEUE_INTERSECT_B` (shade output next bounce). Swap pointers each bounce.
3. **NEE in shade kernel.** Each shade kernel emits one shadow ray into `QUEUE_SHADOW` for NEE, unless the material is purely specular (`isDelta = true`). MIS weights computed in shade, applied when shadow test passes in `stage_shadow`.
4. **Spectral throughput.** Each shade kernel reads `path_lambda[i]` and `path_throughput[i]` from SoA, evaluates `GSampledSpectrum` BSDF, writes updated `path_throughput[i]`. The spectral profile dispatch (`GMaterial.profileIndex`) follows the same constant-memory path as the megakernel.
5. **Neural-cache integration.** The `neural-cache` integrator plugin reads `path_throughput[i]`, `path_pixel[i]` from SoA in `endFrame()` to build its training buffer. No changes to `NeuralCache` training logic — only the data source changes from registers to SoA arrays.

#### Phase B acceptance criteria

- [ ] `astroray.integrator_capabilities("wavefront_path_tracer")["gpuSupported"]` is `True`.
- [ ] Wavefront vs CPU `path_tracer` SSIM ≥ 0.985 at 64 spp on the pkg54 visible-band parity scene.
- [ ] Wavefront vs CPU `path_tracer` SSIM ≥ 0.97 at 64 spp on the NIR band parity scene.
- [ ] Megakernel render output unchanged (all pkg54b SSIM gates still pass).
- [ ] **Performance gate:** Wavefront `path_tracer` is ≥ 1.5× faster than the megakernel `path_tracer` on a mixed-material scene (Disney contact sheet: 7 material types, 512 SPP, measured as end-to-end frame time on RTX 5070 Ti).
- [ ] `restir_di` and `neural-cache` integrators produce visually correct output via wavefront (no numerical acceptance gate for ReSTIR in Phase B — visual inspection only; full gate in Phase C).

---

### Phase C — MIS/NEE parity + megakernel removal

**Estimated effort:** 3 weeks

**Goal:** Wavefront achieves full parity including MIS weighting and spectral upsampling. Remove megakernel code paths. Demonstrate ≥ 2× end-to-end speedup.

#### Files to delete

| File | Reason |
|---|---|
| `src/gpu/path_trace_kernel.cu` | Replaced by wavefront pipeline. |
| `src/gpu/multiwavelength_kernel.cu` | Replaced; `multiwavelength_path_tracer` now dispatches wavefront. |

#### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/multiwavelength_path_tracer.cpp` | `renderGPU()` always uses wavefront (remove `use_wavefront` flag). |
| `plugins/integrators/path_tracer.cpp` | `renderGPU()` always uses wavefront. |
| `plugins/integrators/restir_di.cpp` | Reservoir buffer moved to GPU SoA; resampling stage dispatched by wavefront pipeline. |
| `src/gpu/gpu_renderer.h` | Remove megakernel launch declarations. |
| `module/blender_module.cpp` | Remove megakernel dispatch branches. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg55 complete. |

#### Key design decisions (Phase C)

1. **MIS balance heuristic.** Port the megakernel's power-heuristic MIS weighting (`balanceHeuristic`, Veach 1997) into the wavefront shade → shadow flow. `path_mis_pdf` SoA field carries the BSDF PDF; `stage_shadow` reads it to compute the MIS weight for the NEE contribution.
2. **ReSTIR reservoirs.** Per-pixel `Reservoir` structs (from pkg20) are allocated as a flat GPU buffer (`numPixels × sizeof(Reservoir)`). The wavefront shade stage reads/writes the reservoir for its pixel. Temporal and spatial reuse passes run as additional stages between `STAGE_SHADE` and the next `STAGE_INTERSECT`.
3. **Remove megakernel.** Only after all Phase C acceptance gates pass.

#### Phase C acceptance criteria

- [ ] All pkg54 / pkg54a / pkg54b SSIM gates pass with wavefront (megakernel is deleted; tests must still pass).
- [ ] `multiwavelength_path_tracer` (wavefront) SSIM ≥ 0.985 vs CPU at 64 spp (visible band).
- [ ] `restir_di` (wavefront) temporal-variance test passes (existing pkg24 gate).
- [ ] **Performance gate:** ≥ 2× end-to-end frame time improvement on the Disney contact-sheet scene (7 material types, 1024 SPP) compared to the Phase A megakernel baseline, measured on RTX 5070 Ti.
- [ ] `pytest -q` — all 435+ collected tests pass (or known xfails unchanged).
- [ ] `STATUS.md` updated; pkg55 marked done.

---

## Acceptance (summary, per phase)

| Phase | Key gate |
|---|---|
| A | Intersect parity test bit-exact; megakernel SSIM ≥ 0.985 unchanged |
| B | Wavefront SSIM ≥ 0.985 (visible) / ≥ 0.97 (NIR); ≥ 1.5× speedup on 7-material scene |
| C | All pkg54 SSIM gates pass with megakernel deleted; ≥ 2× speedup on 7-material scene |

---

## Non-goals

- Do not port the rendering pipeline to OptiX (use CUDA-native wavefront with sort-by-material instead). The OptiX SBT trade-off is documented in the research note but rejected for this package.
- Do not change the `Material` plugin interface (C++ virtual methods) unless absolutely required. The shade kernels call device-side `GMaterial` evaluation functions, not the CPU plugin interface.
- Do not implement hardware subsurface scattering or volume scattering in wavefront — those are follow-up packages if ever needed.
- Do not add new material types in this package.
- Do not change the Blender addon UI during pkg55 — the integrator dropdown already exists.

---

## Progress

Phase A:
- [ ] `IntegratorStateSoA` header + allocation helpers
- [ ] `stage_init.cu`
- [ ] `stage_intersect.cu`
- [ ] `queue_dispatch.cpp`
- [ ] Intersect parity test passing
- [ ] CMake integration

Phase B:
- [ ] 7 shade kernels
- [ ] `stage_shadow.cu`, `stage_miss.cu`, `stage_terminate.cu`
- [ ] `material_sort.cu` (CUB radix sort)
- [ ] `wavefront_path_tracer` plugin registered
- [ ] SSIM parity tests passing
- [ ] 1.5× performance gate passing

Phase C:
- [ ] MIS/NEE port
- [ ] ReSTIR reservoir SoA migration
- [ ] Megakernel files deleted
- [ ] 2× performance gate passing
- [ ] Full test suite clean
