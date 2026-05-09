# Wavefront GPU Path Tracing — Research Note

**Date:** 2026-05-10  
**Author:** Claude Code (research session, worktree `angry-mestorf-4a4f76`)  
**Status:** Research signed off — ready to spec pkg55  
**Supersedes:** Nothing (first research note on this topic)

---

## References

| Source | ID | License | Files cited |
|---|---|---|---|
| Laine, Karras, Aila — "Megakernels Considered Harmful: Wavefront Path Tracing on GPUs" | HPG 2013, DOI [10.1145/2492045.2492060](https://dl.acm.org/doi/10.1145/2492045.2492060) | N/A (academic paper) | Entire paper |
| Cycles standalone renderer | [blender/cycles @ c9227ff](https://github.com/blender/cycles/tree/c9227ff33cc79f859d77e493e9a0969955f721be) | Apache-2.0 | `src/kernel/integrator/state.h`, `state_template.h`, `intersect_closest.h`, `shade_surface.h`, `init_from_camera.h`, `src/device/cuda/queue.cpp` |
| PBRT-v4 GPU renderer | [mmp/pbrt-v4 @ eef3a6e](https://github.com/mmp/pbrt-v4/tree/eef3a6ef634a7d83dc98458334dfdfbbe8906d53) | Apache-2.0 | `src/pbrt/wavefront/integrator.cpp`, `workitems.soa`, `workqueue.h` |
| NVIDIA OptiX 8 Programming Guide | [raytracing-docs.nvidia.com](https://raytracing-docs.nvidia.com/optix8/guide/index.html) | NVIDIA proprietary | SBT sections (doc only) |
| PBRT-v4 online book | [pbr-book.org/4ed/Wavefront_Rendering_on_GPUs](https://pbr-book.org/4ed/Wavefront_Rendering_on_GPUs) | CC-BY-NC-ND | Background reading |
| Blender Cycles X announcement | [code.blender.org](https://code.blender.org) | — | Performance numbers |

---

## 1. Why Wavefront — The Warp-Divergence Problem

### The megakernel bottleneck

A megakernel path tracer runs one monolithic CUDA kernel that handles every part of a path: BVH traversal, surface hit evaluation, material sampling, NEE/shadow rays, and accumulation. On CPU this structure is fine — threads are fat and independent. On GPU it is deeply pathological.

NVIDIA GPUs execute threads in groups of 32 called **warps**. All 32 threads in a warp share a single instruction fetch/decode unit: they execute in **SIMT** (Single Instruction, Multiple Thread) lock-step. When different threads branch to different code paths, the hardware serialises the branches — all 32 threads stall while the active subset executes each path in turn. In the extreme (fully divergent warp), a 32-way branch runs 32 serial passes, delivering 1/32 of peak throughput.

Path tracing is maximally divergent by nature. Even if camera rays start coherent, they scatter across a scene containing different materials. After one or two bounces, the probability that two threads in the same warp are evaluating the same material code path drops near zero. Each warp silently serialises into per-material microsequences.

The second problem is **register pressure**. A megakernel that includes BSDF evaluation code for Lambertian, Disney, Dielectric, Metal, and Thin Glass simultaneously must allocate registers for all of those paths — even though any given thread only uses one. The GPU register file is finite and shared among concurrent warps. A kernel using 128 registers per thread can run 8 warps concurrently on an SM that supports 1024 concurrent threads; a kernel using 64 registers per thread can run 16. High register counts directly reduce the **thread-level parallelism** the hardware uses to hide memory latency.

Laine, Karras, and Aila quantified this in their 2013 HPG paper. They measured a path tracer with five material types on a GTX 580: the megakernel delivered roughly **2–3× lower throughput** than expected from compute peak, with the gap widening as material diversity increased. In scenes with a single dominant material, the megakernel performed acceptably; in production-grade scenes with mixed materials, **wavefront delivered 2× or better speedup** over the megakernel (Section 5, Table 1). The CMU 15-618 wavefront project that reproduced their results set a conservative target of >1.3× for simple scenes and >2× for complex/mixed-material scenes, citing Laine 2013 directly.

Cycles X (Blender 3.0, December 2021) adopted wavefront as its primary GPU architecture and documented **2.2× speedup** on the Koro production scene (52 s vs 116 s in Blender 2.93) and **3–5× speedup on volume-heavy scenes** relative to the old megakernel Cycles.

### What wavefront fixes

The insight in Laine 2013 §3 is simple: if you sort rays by what they are about to do before launching each kernel, every thread in a warp executes the same code. **Warp efficiency at kernel entry approaches 100%.** The per-stage kernel is also smaller, so its register count is lower, which increases occupancy and improves latency hiding.

The trade-off is queue management overhead: rays must be written to typed queues between stages rather than being processed in a single pass. On modern GPUs with fast global memory bandwidth, this overhead is well below the savings from divergence elimination (Laine 2013 §4.1 measured queue overhead at 5–15% of stage kernel time).

---

## 2. SoA State Layout

### What "SoA" means here

In the **megakernel** world, each GPU thread owns one path and carries its state in local registers or a small shared struct. In **wavefront**, thousands of in-flight paths are parked in global memory between stages. The layout question is: one array-of-structs (`path[i].field`) or many struct-of-arrays (`field[i]`)?

SoA wins decisively because of **coalesced memory access**. When warp thread 0 reads `ray_origin_x[0]` and thread 31 reads `ray_origin_x[31]`, those 32 floats form a contiguous 128-byte line — a single L2 transaction. With AoS (`path[0].origin.x`, `path[32].origin.x`, …), the 32 addresses are stride-`sizeof(path)` apart, producing 32 separate transactions, burning 32× the bandwidth.

### Cycles SoA template

Cycles defines its SoA state in `src/kernel/integrator/state_template.h` (blender/cycles @ c9227ff). The macro `INTEGRATOR_STATE(state, struct, field)` expands to `kernel_integrator_state.struct.field[state]` on GPU — a plain indexed array access. The template lists the following field groups:

**`path` sub-struct** (per-bounce scalar state):

| Field | Type | Bytes | Purpose |
|---|---|---|---|
| `render_pixel_index` | uint32_t | 4 | Pixel coordinate → accumulation buffer |
| `sample` | uint32_t | 4 | Sample index within pixel |
| `bounce` | uint16_t | 2 | Total bounce depth |
| `transparent_bounce` | uint16_t | 2 | Transparent-only depth |
| `diffuse_bounce` | uint16_t | 2 | Diffuse depth counter |
| `glossy_bounce` | uint16_t | 2 | Glossy depth counter |
| `transmission_bounce` | uint16_t | 2 | Transmission depth counter |
| `volume_bounce` | uint16_t | 2 | Volume scatter depth |
| `queued_kernel` | uint16_t | 2 | Which stage this path enters next |
| `rng_pixel` | uint32_t | 4 | Per-pixel RNG seed |
| `rng_offset` | uint16_t | 2 | Per-bounce RNG offset |
| `flag` | uint32_t | 4 | Visibility/termination flags |
| `optical_depth` | float | 4 | Volume transmission accumulator |
| `mis_ray_pdf` | float | 4 | MIS PDF for last specular event |
| `min_ray_pdf` | float | 4 | Min PDF along path (MIS guard) |
| `continuation_probability` | float | 4 | Russian roulette survival |
| `throughput` | PackedSpectrum | 12–16 | Accumulated radiance weight |
| `shader_sort_key` | uint32_t | 4 | Material type key for sort-based dispatch |

**`ray` sub-struct** (~32 bytes):
`P` (packed_float3), `D` (packed_float3), `tmin` (float), `tmax` (float), `time` (float).

**`isect` sub-struct** (~24 bytes):
`t`, `u`, `v` (float ×3), `prim`, `object`, `type` (int ×3).

**Queue counter** (`IntegratorQueueCounter`):
`num_queued[DEVICE_KERNEL_INTEGRATOR_NUM]` — one atomic counter per stage type.

### PBRT-v4 SoA work items

PBRT-v4 (mmp/pbrt-v4 @ eef3a6e) takes a slightly different approach: instead of one giant state array, each queue holds typed SoA work items declared in `src/pbrt/wavefront/workitems.soa`. The `WorkQueue<T>` template (in `workqueue.h`) extends `SOA<T>` and adds an atomic counter:

```
// From pbrt-v4 workitems.soa (Apache-2.0)
soa RayWorkItem {
    Ray ray;           // packed: origin + dir
    int depth;
    int pixelIndex;
    SampledWavelengths lambda;      // 4 × float lambda + 4 × float pdf = 32 B
    SampledSpectrum beta, r_u, r_l; // 3 × 16 B = 48 B of spectral throughput
    LightSampleContext prevIntrCtx;
    Float etaScale;
    int specularBounce;
    int anyNonSpecularBounces;
};

soa PixelSampleState {
    Float filterWeight;
    Point2i pPixel;
    SampledWavelengths lambda;
    SampledSpectrum L;
    SampledSpectrum cameraRayWeight;
    VisibleSurface visibleSurface;
    RaySamples samples;
};
```

The `SOA<T>` macro-generated code stores each field as a separate flat array, accessed via `items.field[i]`.

### Astroray IntegratorState SoA mapping

Our current megakernel carries path state in registers only — there is no persistent per-path struct between kernel launches. The wavefront transition requires allocating a persistent SoA buffer that covers all in-flight paths simultaneously.

The following mapping mirrors the PBRT-v4 `RayWorkItem` pattern against our existing `gpu_types.h` types:

| SoA array | Source type | Bytes/ray | Alignment notes |
|---|---|---|---|
| `ray_origin[N]` | 3 × float | 12 | Pad to 16 for vec4 coalescing |
| `ray_dir[N]` | 3 × float | 12 | Pad to 16 |
| `ray_tmin[N]`, `ray_tmax[N]` | 2 × float | 8 | Pack into float2 |
| `hit_t[N]`, `hit_u[N]`, `hit_v[N]` | 3 × float | 12 | From `GHitRecord.t/u/v` |
| `hit_prim[N]`, `hit_mat[N]` | 2 × int | 8 | From `GHitRecord.primId/materialId` |
| `hit_normal[N]` | 3 × float | 12 | Pad to 16 |
| `hit_tangent[N]` | 3 × float | 12 | Pad to 16 (only needed for shade stage) |
| `hit_bitangent[N]` | 3 × float | 12 | Pad to 16 |
| `hit_flags[N]` | uint8 × 2 | 2 | frontFace + isDelta |
| `path_pixel[N]` | uint32 | 4 | Framebuffer address |
| `path_sample[N]` | uint32 | 4 | Sample index |
| `path_bounce[N]` | uint16 | 2 | Bounce depth |
| `path_flags[N]` | uint32 | 4 | Visibility + termination flags |
| `path_rng_seed[N]` | uint32 | 4 | Per-pixel seed |
| `path_rng_offset[N]` | uint16 | 2 | Per-bounce offset |
| `path_throughput[N]` | `GSampledSpectrum` | 16 | 4 × float spectral weight |
| `path_lambda[N]` | `GSampledWavelengths` | 32 | 4 × float lambda + 4 × float pdf |
| `path_mis_pdf[N]` | float | 4 | MIS ray PDF |
| `path_cont_prob[N]` | float | 4 | Russian roulette probability |
| `path_queued_kernel[N]` | uint16 | 2 | Next stage for this path |
| `path_sort_key[N]` | uint32 | 4 | Material type (for shade dispatch) |

**Total per-ray state:** approximately 220 bytes for the full path + hit state, of which **48 bytes is spectral** (lambda[4] + pdf[4] + throughput[4]).

**Coalescing constraints:** All arrays should be 128-byte aligned (two cache lines on Ampere/Ada). The `ray_origin`, `hit_normal`, `hit_tangent` fields should be padded to 16 bytes (`float4` loads) because vec3 loads cannot be coalesced — the GPU issues 12-byte reads which are not power-of-two and break the coalescing unit. Use `float4` with `w = 0` as padding rather than separate float arrays.

**`GHitRecord` alignment note:** The current `GHitRecord` in `gpu_types.h` stores `tangent` and `bitangent`, which are only needed in the shade stage, not the intersect stage. In the wavefront design, defer writing these fields until shade, since the intersect stage can output minimal hit data (t, u, v, prim, mat, normal). This reduces intersect→shade bandwidth by ~24 bytes/ray.

---

## 3. Stage Queues

### Cycles stage list

Cycles (blender/cycles @ c9227ff, `src/kernel/integrator/`) defines these stages as `DEVICE_KERNEL_INTEGRATOR_*` enum values:

1. `INIT_FROM_CAMERA` — generate camera rays, initialise SoA state
2. `INTERSECT_VOLUME_STACK` — initialise volume stack at camera position
3. `INTERSECT_CLOSEST` — BVH traversal for primary/bounce rays
4. `SHADE_SURFACE` — evaluate BSDF, sample next direction, emit NEE shadow ray
5. `SHADE_SURFACE_RAYTRACE` — shade surface with raytraced AO/reflections
6. `SHADE_SURFACE_MNEE` — manifold next-event estimation for caustics
7. `SHADE_VOLUME` — in-scattering / absorption along ray
8. `SHADE_SHADOW` — evaluate shadow ray transmittance
9. `SHADE_BACKGROUND` — env map miss
10. `SHADE_LIGHT` — direct hit of a light source

The `queued_kernel` field in path state encodes which stage each path proceeds to. After each stage, `integrator_path_next()` atomically increments `num_queued[next_kernel]`. The host dispatch loop checks these counters and launches the appropriate kernel for non-empty queues.

### PBRT-v4 stage list

PBRT-v4 (`src/pbrt/wavefront/integrator.cpp`, mmp/pbrt-v4 @ eef3a6e) uses a slightly different decomposition with explicit typed queues:

1. `GenerateCameraRays` → pushes to `RayQueue[0]`
2. `IntersectClosest` (via aggregate) → routes to `EscapedRayQueue`, `HitAreaLightQueue`, or `MaterialEvalQueue`
3. `HandleEscapedRays` — env map miss
4. `HandleEmissiveSurfaces` — direct hit on area lights
5. `EvaluateMaterialsAndBSDFs` → samples BSDF, pushes to `RayQueue[1]`, `ShadowRayQueue`
6. `TraceShadowRays` → reads `ShadowRayQueue`, accumulates radiance
7. `SampleSubsurface` — BSSRDF materials
8. `SampleMediumInteraction` — volumetric scatter

### Recommended stage list for Astroray

Astroray's integrators are: `path_tracer`, `multiwavelength_path_tracer`, `restir_di`, `neural-cache`. We do not currently have subsurface scattering or volumes in the GPU path. The recommended first-pass stage list is:

| Stage | Queue feeds | Action |
|---|---|---|
| `STAGE_INIT` | → `QUEUE_INTERSECT` | Sample camera, write ray SoA, init wavelengths |
| `STAGE_INTERSECT` | → `QUEUE_SHADE` or `QUEUE_MISS` | BVH traversal, write hit record SoA |
| `STAGE_SHADE` | → `QUEUE_SHADOW`, `QUEUE_INTERSECT`, `QUEUE_TERMINATE` | BSDF eval, NEE shadow ray, sample next direction |
| `STAGE_SHADOW` | → `QUEUE_SHADE` (radiance accumulate) | Shadow ray BVH, write transmittance flag |
| `STAGE_MISS` | → `QUEUE_TERMINATE` | Env map eval, write to accumulation buffer |
| `STAGE_TERMINATE` | — | Russian roulette, write final pixel radiance |

Two queues (`QUEUE_INTERSECT` and `QUEUE_SHADE`) are **double-buffered** — the init stage writes to queue A, the intersect stage reads queue A and writes to queue B (shade), the shade stage reads queue B and writes back to queue A (next bounce). This mirrors the PBRT-v4 `RayQueue[0/1]` pattern.

**ReSTIR extension (Phase B follow-up):** ReSTIR requires reservoir storage per pixel and a spatial-reuse pass after initial sample selection. This fits as an additional `STAGE_RESTIR_RESAMPLE` between `STAGE_SHADE` and the next `STAGE_INTERSECT` for the selected sample's validation ray. ReSTIR and the neural-cache integrator can re-use the same SoA state buffers and intersect/shade stages — the integrator plugin selects which stages are dispatched each frame.

---

## 4. Material Dispatch

### The problem

The shade stage evaluates BSDF for whichever material was hit. If all material types land in the same kernel, we reintroduce divergence — exactly the problem wavefront was designed to solve.

### Option A: Sort-by-material (Cycles approach) — **Recommended**

Cycles stores a `shader_sort_key` in path state. After `STAGE_INTERSECT`, a sorting pass (CUB `DeviceRadixSort`) orders paths by material type. Shade kernels are then launched per-material-type with contiguous work, guaranteeing warp coherence.

For Astroray's 7 material types (`GMAT_LAMBERTIAN`, `GMAT_METAL`, `GMAT_DIELECTRIC`, `GMAT_DIFFUSE_LIGHT`, `GMAT_DISNEY`, `GMAT_THIN_GLASS`, `GMAT_CLOSURE_GRAPH`), this means 7 sub-queues or 7 kernel invocations per shade stage. The sort cost at N paths is O(N) radix sort — negligible for N ≥ 65 536. Cycles uses `sort_key_counter[]` and `sort_partition_key_offsets` arrays to avoid a full sort when work is skewed toward one material type (most paths in the same material skip the sort entirely).

**Advantages:** No API dependencies, works on any CUDA/HIP/Metal backend, allows per-material kernel tuning (different register budgets), straightforward to add material types without touching the dispatch loop.

**Implementation:** Add `path_sort_key[N]` (uint32, holds `GMaterialType`) to the SoA state. Write it in `STAGE_INTERSECT`. Before `STAGE_SHADE`, launch one `shade_<type>` kernel per non-empty material bucket.

### Option B: Uber-shader

One `shade_surface` kernel with a switch on `GMaterial.type`. Simple to implement — it's essentially what the megakernel already does. However, it reintroduces warp divergence at the branch: once two threads in the same warp hit different materials, the switch serialises. For 7 material types with even distribution, worst-case divergence is 7× serial execution per warp, recovering nothing from wavefront except the intersect/shade separation.

**Not recommended** as a permanent solution. Acceptable only as a Phase A temporary stub.

### Option C: OptiX Shader Binding Table

The OptiX SBT maps each geometry instance to a per-material closest-hit/any-hit shader. The hardware automatically dispatches to the correct shader function; no CPU-side sort is needed. SBT geometry and material parameters are stored in separate global arrays to avoid redundant storage (a design confirmed by NVIDIA's 2024 SBT optimization blog post).

**Trade-off analysis:** OptiX SBT achieves full warp coherence at dispatch without a sort, and integrates naturally with hardware RT cores. However:
- It requires porting the entire rendering pipeline to OptiX — including BVH build (`optixAccelBuild`), ray launch (`optixLaunch`), and program group setup.
- It couples the material interface to the OptiX program group API, making it harder to add CPU fallback or HIP portability.
- It is incompatible with Astroray's current `astroray_core` CUDA backend architecture, which builds BVH and dispatches kernels without OptiX.

**Decision:** Do not use OptiX for pkg55. The sort-by-material approach achieves equivalent warp efficiency for 7 material types at a small sorting overhead. If Astroray ever moves to hardware RT cores (a separate, large architectural decision), OptiX SBT becomes worth reconsidering.

---

## 5. Integration with pkg54+ Spectral Path

### The spectral state size problem

Each in-flight wavefront path carries:

| Field | Type | Bytes |
|---|---|---|
| `lambda[4]` (sampled wavelengths) | float×4 | 16 |
| `pdf[4]` (wavelength sampling PDF) | float×4 | 16 |
| `throughput[4]` (spectral weight) | float×4 | 16 |

**Spectral overhead: 48 bytes per ray.**

For a concurrent path count of N = 65 536 (Cycles' default busy-states value), total spectral memory is 65 536 × 48 = **3.1 MB** — well within the 24 GB VRAM on an RTX 5070 Ti, and also within the 6–8 GB budget of smaller GPUs we target. The full path state (including ray, hit record, bounce counts, RNG) totals roughly 220 bytes/ray × 65 536 = **14.4 MB** of SoA buffers. Even at 4× Cycles' default (262 144 paths), total state is ~57 MB — fine.

### Half-precision optimization (optional)

If state memory becomes a constraint (e.g., targeting RTX 3060 Ti with 8 GB and many concurrent paths), consider storing `lambda[4]` in `half2×2` (8 bytes) and `throughput[4]` in `half2×2` (8 bytes). The wavelength range 360–830 nm maps to fp16 with sub-nanometre precision. Throughput values near zero need careful handling (flush-to-zero in fp16), but throughput is typically bounded by Russian roulette before underflow becomes pathological. This halves spectral state to 24 bytes/ray (matching the original estimate in the pkg55 deferred entry). Defer until Phase C when actual memory pressure is measured.

### Wavelength sampling in the wavefront pipeline

`GSampledWavelengths` is fixed for the lifetime of a path — it is sampled once in `STAGE_INIT` and only modified if a delta transmission event terminates secondary wavelengths (`terminateSecondary()`). The `STAGE_SHADE` kernel reads `path_lambda[i]` and passes it to the material BSDF; it writes updated `path_throughput[i]` after the BSDF evaluation. This is a straightforward SoA read-modify-write with no data dependencies between paths — ideal for GPU parallelism.

### Spectral profile table (pkg54a)

The per-material spectral profile index (`GMaterial.profileIndex`, pointing into `G_MAX_PROFILES × G_PROFILE_SAMPLES` constant memory) survives unchanged into the wavefront design. The shade kernel reads `path_mat[i]` → `GMaterial` → `profileIndex` → profile table — same access pattern as the megakernel. No structural changes required.

### Integration with `multiwavelength_path_tracer`

The wavefront design should support all four of Astroray's integrators. The key: the integrator plugin determines which *stages* are dispatched each frame. `path_tracer` (RGB, no spectral) skips the lambda/pdf arrays and uses a simple 3-float throughput. `multiwavelength_path_tracer` allocates the full 48-byte spectral state. `restir_di` adds a reservoir buffer (per-pixel, not per-path) and a resampling stage. `neural-cache` adds a training buffer flush in `endFrame()`. All can share the same SoA state arrays — unused fields cost memory but no compute.

---

## 6. Migration Plan

The megakernel in `src/gpu/path_trace_kernel.cu` and `src/gpu/multiwavelength_kernel.cu` must stay fully functional throughout migration. All phases must preserve the SSIM acceptance gates from pkg54b (≥ 0.985 at 64 spp, plateau ≥ 0.996 at 512 spp for the visible-band parity scene).

### Phase A — SoA state infrastructure + intersect queue (estimated 3–4 weeks)

**Goal:** Allocate the SoA path state buffers and wire the first two stages (`STAGE_INIT` and `STAGE_INTERSECT`) as a standalone CUDA pipeline. The megakernel continues to produce all final-pixel output; Phase A only validates that the new intersect stage produces identical hit records to the megakernel's internal BVH call.

**Tasks:**
1. Add `IntegratorStateSoA` struct in a new header (`include/astroray/integrator_state_soa.h`) with all arrays listed in §2.
2. Allocate SoA buffers via `cudaMalloc` at renderer startup; size by `max_concurrent_paths = max(max_threads, 65536) * 16` (matching Cycles default).
3. Implement `stage_init_from_camera` CUDA kernel: reads camera params, writes ray SoA, samples `GSampledWavelengths`, writes `path_pixel`, `path_sample`, `path_throughput = {1,1,1,1}`.
4. Implement `stage_intersect` CUDA kernel: reads ray SoA, runs BVH traversal (reuse `gpu_bvh_hit`), writes hit record SoA and `path_sort_key`.
5. Add queue counter arrays and a host-side dispatch loop that checks `num_queued[]` and launches stages.
6. Add a validation mode: after `STAGE_INTERSECT`, compare `hit_t[i]` / `hit_mat[i]` against the megakernel's internal hit for the same camera ray. Assert bit-identical results.

**Verify:** New intersection parity test passes. Megakernel render output unchanged. No SSIM regression on any acceptance scene.

### Phase B — Shade queue + material dispatch (estimated 4 weeks)

**Goal:** Wire `STAGE_SHADE`, `STAGE_SHADOW`, `STAGE_MISS`, and `STAGE_TERMINATE`. Implement per-material sub-kernels. The wavefront integrator produces its own pixel output in parallel with the megakernel; compare SSIM.

**Tasks:**
1. Implement `shade_lambertian`, `shade_metal`, `shade_dielectric`, `shade_disney`, `shade_thin_glass`, `shade_diffuse_light`, `shade_closure_graph` kernels — one per `GMaterialType`. Each reads the SoA hit record + wavelengths + material params; evaluates BSDF; writes `path_throughput`, next ray direction, and pushes to `QUEUE_SHADOW` (NEE) and `QUEUE_INTERSECT` (indirect).
2. Implement the sort-by-material pass: CUB `DeviceRadixSort` on `path_sort_key` after `STAGE_INTERSECT`. Launch each shade kernel for its bucket.
3. Implement `stage_shadow`: reads shadow ray SoA, runs a shadow-BVH any-hit, accumulates NEE radiance into pixel accumulation buffer.
4. Implement `stage_miss`: env map lookup for escaped rays, accumulate into pixel buffer.
5. Implement `stage_terminate`: Russian roulette, final radiance write.
6. Add `wavefront_path_tracer` as a new integrator plugin that dispatches the wavefront pipeline. Add `gpuSupported = true`.
7. Parity tests: wavefront SSIM ≥ 0.985 vs CPU `path_tracer` at 64 spp on the pkg54 parity scene. Performance: wavefront must be ≥ 1.5× faster than megakernel on the mixed-material contact-sheet scene (4+ distinct material types, 1024 SPP).

**Verify:** All pkg54/pkg54a/pkg54b acceptance tests pass. New wavefront SSIM gate passes. At least 1.5× speedup measured on RTX 5070 Ti (or whatever hardware is available).

### Phase C — NEE/MIS integration + megakernel removal (estimated 3 weeks)

**Goal:** Wavefront integrator achieves full parity with the megakernel including NEE/MIS and spectral profiles. Remove megakernel code paths.

**Tasks:**
1. Port MIS weighting from the megakernel's NEE/BSDF balance into the wavefront shade → shadow flow.
2. Validate `multiwavelength_path_tracer` via wavefront: spectral throughput SSIM ≥ 0.985 (pkg54b gate).
3. Validate ReSTIR: reservoir update wired to the wavefront shade stage; spatial reuse pass dispatched after shade.
4. Remove `src/gpu/path_trace_kernel.cu` megakernel. Keep `src/gpu/multiwavelength_kernel.cu` megakernel as a secondary reference only until pkg55 Phase C passes all tests, then remove.
5. Performance target: ≥ 2× end-to-end frame time improvement vs removed megakernel on a scene with ≥ 4 material types (e.g., the Disney contact sheet scene).
6. Update `STATUS.md`, close pkg55.

---

## 7. Risks and Open Questions

### Risk 1: Queue memory pressure on low-VRAM GPUs

The SoA buffer for 65 536 concurrent paths is ~14 MB at full state. This is fine on the RTX 5070 Ti (24 GB), but small laptops with 4–6 GB VRAM may need a tunable `max_concurrent_paths` parameter. Mitigation: expose `ASTRORAY_CONCURRENT_PATHS_FACTOR` (matching Cycles' `CYCLES_CONCURRENT_STATES_FACTOR`). Default to Cycles' formula: `max(max_num_threads, 65536) * 16`.

### Risk 2: Sort overhead dominates on simple scenes

When all rays hit the same material (e.g., a Lambertian Cornell box), the sort pass is pure overhead. Mitigation: skip the sort if the queue counter shows only one non-empty material bucket. The `sort_key_counter` check at the host level adds negligible latency.

### Risk 3: Hit record bandwidth between intersect and shade

Phase A separates the intersect and shade kernels, forcing hit record data (point, normal, tangent, bitangent = ~52 bytes/ray) through global memory. If global memory bandwidth is the bottleneck, we may need to defer tangent/bitangent to the shade stage (recompute from geometry rather than storing). **Open question:** measure bandwidth utilisation with NSight Compute before optimising.

### Risk 4: RNG state per path

The current megakernel uses a per-pixel Halton sequence, fully deterministic. In wavefront, paths are reordered by material type and may be dispatched in different order across frames. The RNG must be keyed by `(pixel_index, sample_index, bounce)`, not by thread ID, to preserve reproducibility. This is standard practice (Cycles uses `rng_pixel` + `rng_offset` for exactly this reason) but must be verified before Phase A passes the regression tests.

### Risk 5: Compatibility with neural-cache training buffer

The `neural-cache` integrator accumulates a training buffer in `endFrame()`. In the megakernel, all per-path data is immediately available. In wavefront, path data is distributed across SoA arrays between stages; the training buffer flush must read from those arrays rather than registers. This is architecturally cleaner (data is already in global memory) but requires updating the `NeuralCache` backend to read from SoA rather than inline registers. Estimate: 1–2 days additional work in Phase B.

### Risk 6: pkg54c (Jakob-Hanika GPU upsampling) interaction

pkg54c (deferred follow-up) adds GPU spectral upsampling. If it lands before pkg55 Phase B, its upsampled-spectrum `GSampledSpectrum` output must flow into the SoA `path_throughput` arrays. This is a clean interface change — the shade kernel writes `path_throughput` regardless of where the spectrum came from. No conflict.

### Open question: optimal concurrent path count

Cycles uses `max(max_num_threads, 65536) * 16` = ~1 M paths on an RTX 3080. For Astroray's SM count (RTX 5070 Ti has 70 SMs × 1536 threads = 107 520 max threads → formula gives ~1.7 M paths). That is 1.7 M × 220 bytes ≈ 374 MB of SoA state. Still manageable, but warrants a measured benchmark to find the optimal trade-off between queue fill rate and memory occupancy.

### Open question: ReSTIR reservoir layout

pkg20–pkg24 implement ReSTIR reservoirs as CPU-side structs. Moving to wavefront means reservoirs must live in GPU global memory as SoA arrays (one reservoir per pixel). The reservoir struct is ~40 bytes; a 1920×1080 frame needs ~83 MB of reservoir storage. Compatible with the wavefront design but requires explicit discussion with the ReSTIR implementation in pkg24 before Phase B begins.
