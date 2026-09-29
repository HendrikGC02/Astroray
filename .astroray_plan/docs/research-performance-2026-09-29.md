# Render performance research: closing and beating the Cycles gap (2026-09-29)

Owner request 2026-09-29: find and plan ways to make Astroray substantially faster,
close the gap to Cycles, then beat it, including new or obscure techniques.
This document is research and planning only. No engine code changed.

Measured on the RTX 5070 Ti (driver 616.56) against the `Astroray-al-293/build_cuda`
main build (`.pyd` 2026-09-29 13:46), under the GPU lock, with Blender 5.2 Cycles on
the same machine. Specs filed: **pkg298**, **pkg299**, **pkg300**.

---

## 1. Current state: where the time goes

### 1.1 Head-to-head against Cycles (same geometry, same machine)

The scene is a Cornell box (12 triangles, 1 emissive quad, diffuse only). The
"heavy" variant adds two displaced spheres, for 2,000,012 triangles. Both engines load
identical triangle arrays from `.npy`. Settings: 1024², 256 spp, max bounces 8, no
denoiser, no adaptive sampling. Times are wall-clock per `render()` call: mean of
warm repeats, first call dropped for Cycles.

| Scene | Astroray GPU | Cycles OptiX | Cycles CUDA | Astroray vs OptiX |
|---|---|---|---|---|
| Cornell, 12 tris | **16.5 s** | 4.9 s | 4.9 s | **3.4× slower** |
| Cornell + 2 M tris | **35.1 s** | 5.3 s | 12.8 s | **6.6× slower** |

Two things follow from the table:

- **Hardware traversal.** Cycles' own OptiX/CUDA ratio is 1.0× on the trivial scene
  and **2.4× on the 2 M-triangle scene**. The RT cores are worth 2.4× end to end once
  geometry matters, and Astroray does not use them.
- **Shading.** Even on 12 triangles, where traversal is almost free, Astroray is
  3.4× slower. That gap is shading and scheduling, not the BVH.

The two renders were checked visually: same framing, same geometry. Cycles looks
brighter because of its view transform, which does not affect timing. Evidence:
`reports/perf-2026-09-29/astro_heavy.png` and `reports/perf-2026-09-29/cycles_heavy.png`.

### 1.2 GPU kernel attribution (`ASTRORAY_PROFILE=1`, 512², 64 spp, depth 8)

| Stage | Cornell diffuse | Cornell glass | Heavy 2 M tris | REG / blocks per SM |
|---|---|---|---|---|
| `stageShadeBucketedKernel` | **71 %** | **72 %** | 35 % | 254 / 1 |
| `stageIntersectQueuedKernel` | 11.5 % | 11 % | **44 %** | 192 / 1 |
| `stageShadowKernel` | 6 % | 5.5 % | **16 %** | 108 / 2 |
| `stageRegenKernel` | 11 % | 11 % | 5.5 % | 108 / 2 |

- **Shade kernel resources.** Per `cuobjdump`, all 128 template variants of the shade
  kernel sit at REG 254 with **STACK 3.8 to 8.7 KB per thread**. Even the leanest
  variant, with every feature axis false, is at 254 / 3.8 KB. The shade share has
  grown since pkg155 measured 44 to 52 % in 2026-07.
- **Intersect kernel resources.** Variants range from 148 to 223 registers, with 600 to
  1960 B of stack. It was 128 registers in 2026-07. A lean BVH traversal kernel needs
  roughly 40 to 70.
- **Fixed per-render cost.** On the heavy scene at 16², 1 spp, each call costs 1.7 s
  on CPU and 2.6 s on GPU. By code reading, `Renderer::buildAcceleration()`
  (`include/raytracer.h:4618`) rebuilds the whole binary SAH BVH on one thread on
  **every** `render()` (`module/blender_module.cpp:2390`), unless `skip_upload` is set.
  The extra ~0.9 s on GPU is flatten and upload work. pkg298 Phase 0 confirms both
  with timers.
- **Occupancy at low resolution.** The path pool is `width*height`
  (`gpu_wavefront_snapshot.cu:1179`). At 256² it is 65 k paths, and throughput drops
  18 % against 1024² (13.4 vs 16.3 Msamples/s). Viewport resolutions lose more.
- **What is not a problem.** There are no streams, CUDA graphs, sorting or prefix
  scans, only atomic queue appends. There are about 1,400 kernel launches per 64-spp
  render. At a few µs each, launch overhead is under 1 % and not a lever.

### 1.3 Counters are blocked

Nsight Compute 2025.1 and Nsight Systems 2024.6 are installed, but counter collection
fails with `ERR_NVGPUCTRPERM`, as it did in 2026-08. Without counters we cannot tell
whether the shade kernel is bound by local-memory spill traffic, latency or
divergence. **Owner action:** enable it once, as admin, via NVIDIA App or Control Panel
> Developer > Manage GPU Performance Counters > "Allow access to all users".

### 1.4 A lean kernel has already beaten this

pkg155 measured the 2026-05 Phase-A multiwavelength megakernel at **20.3 ms of kernel
time** for cornell_diffuse at 256², 64 spp, depth 8. On this Cornell, scaling Cycles
OptiX's 4.9 s to that workload gives about 77 ms. Today's Astroray takes about 290 ms.

The May kernel lacked most of today's features and had known correctness bugs, so the
comparison is indicative only. It still shows that on simple scenes the hardware can
beat Cycles about 3× with a lean spectral kernel. The ~13× since then is
**feature-accretion cost paid by every scene**, whether or not it uses those features.
The light-tree descent runs for a single lamp. The spectral BSDF union and the NEE
section each want about 160 registers on a 95-register base (`pkg174` ledger).

---

## 2. What Cycles does, and what that implies

- **Traversal.** Cycles uses OptiX hardware traversal on RTX: IAS over GAS, OptiX
  curves, and motion. The CUDA backend uses its own BVH2. We measured 2.4× between
  them on 2 M triangles.
- **Wavefront.** Cycles uses SoA integrator state, compaction, "most-queued kernel
  next" scheduling, and **sorting by shader for `shade_surface` only**
  (developer.blender.org kernel_scheduling). Astroray already has a similar wavefront
  and buckets by 7 material *types*, not by shader.
- **Register budget.** `kernel/device/cuda/config.h` sets
  `GPU_KERNEL_BLOCK_NUM_THREADS 384`, `GPU_KERNEL_MAX_REGISTERS 168` and
  `__launch_bounds__(384, 65536/(384*168))`. That is 12 warps per SM, deliberately
  spilling above 168 registers. Astroray runs 256 threads at 254 registers, which is
  8 warps per SM, with no launch bounds. pkg174 found `__launch_bounds__(256,2)`
  "ignored on sm_120". That finding should be re-checked with `__maxnreg__` and a
  384-thread block.
- **Specialisation.** Cycles compiles SVM node groups behind `KERNEL_FEATURE_NODE_*`
  masks and builds OptiX pipelines per requested feature set. Metal got scene
  specialisation in 3.5. Astroray has 7 compile-time bool axes on shade and none for
  lights or material mix.
- **Spectral is not the cause.** None of this required Cycles to be clever about
  spectra. Astroray's 4-λ hero sampling costs about as much as RGB (Wilkie 2014), so
  spectral rendering is **not** the explanation for the gap.

---

## 3. Ranked opportunities

Score = impact × confidence ÷ cost, each on 1 to 5. The gains are for the two
benchmark scenes above.

| # | Item | Expected gain (evidence) | Conf. | Cost | Score | Spec |
|---|---|---|---|---|---|---|
| 1 | **Stop rebuilding the BVH every `render()`**: dirty-flag cache, then a parallel binned-SAH CPU build | Removes 1.7 to 2.6 s per call at 2 M tris (measured). Parallel build ~6 to 8× on the rest. Improves viewport geometry edits, animation frames and repeat renders | 5 | 1 | **25** | pkg298 |
| 2 | **OptiX 9.1 hardware traversal** for the intersect and shadow stages (pbrt-v4 pattern: OptiX raygen consumes the wavefront queue and writes the existing hit buffers; shading stays CUDA). GAS/IAS are built on the device, so the GPU path no longer needs the CPU BVH | Heavy scene 35 s → ~15 to 17 s (traversal is 60 % of kernel time; RT cores gave Cycles 2.4× end to end here, and typically 3 to 6× on traversal alone). Also frees the 148 to 223-register intersect kernel | 5 | 4 | 6.3 | pkg299 |
| 3 | **Shade-kernel diet: scene specialisation + register budget.** (a) Counters on, attribute spill vs latency. (b) Cycles-style budget sweep (`__maxnreg__` 128/168, 384 threads). (c) Specialise on what the scene contains: light count and types (skip light-tree descent for ≤ N lights), a material-type mask, closure opcode set. (d) Finer sort key (material id) | Simple scene: shade is 71 % of 16.5 s. A 2 to 3× shade cut → ~7 to 9 s. The May kernel is the existence proof of a much larger ceiling | 3 | 3 | 4 × 3 ÷ 3 = 4 (high variance) | pkg300 |
| 4 | **Path-pool floor** of ~1 to 2 M states regardless of resolution, as Cycles sizes by device | +10 to 20 % at viewport and preview resolutions (measured 18 % at 256²) | 4 | 1 | 12, but small absolute | pkg298 |
| 5 | **Embree 4 CPU backend** (Apache-2.0) behind the CPU oracle, keeping `BVHAccel` as a switchable reference | CPU traversal is scalar binary with a virtual `Hittable` call per primitive; Embree gives multi-× traversal plus multi-threaded build. **Faster CPU suite = faster dev loop** (3,600 tests) | 3 | 3 | 3 | future |
| 6 | **CUDA 13.x ptxas** for AOT sm_120 (pkg155 found driver-JIT from compute_89 PTX beat AOT sm_120 12.8 by 1.7×; newer ptxas may flip this) | 0 to 1.7× on shade, unknown. One rebuild to find out | 2 | 1 | 2 to 5 | pkg300 Phase 0 |
| 7 | **Slim traversal data** (vertex-only hot array, shading data after the hit) and **CWBVH** (Ylitie 2017: 1.9 to 2.1× on incoherent rays) | Only as a fallback if pkg299 is rejected. On RTX, #2 subsumes it | 3 | 3 | low | none |
| 8 | **SAH TLAS** (the TLAS is one flat leaf; per-ray cost is linear in instance count, per the `scene_upload.cu:532` TODO) | Large for instanced scenes (forests, particles), zero for the benchmarks. Subsumed by the OptiX IAS in #2 | 4 | 2 | medium | pkg299 |
| 9 | **Time-to-quality** (equal-time error, not samples/s): adaptive sampling default, light tree only when many lights, QMC (pkg297), guiding (pkg136, paused) | Often 1.5 to 3× to target error in Cycles' experience. Stage-0e owns the measurement | 3 | 2 | medium | existing |

Not recommended now:

- **CUDA graphs and streams.** Launch overhead is under 1 %.
- **Megakernel return.** It regressed identically; the problem is feature accretion,
  not architecture.
- **NRC for speed.** It is biased; science use needs unbiased estimates.
- **ReSTIR PT for offline.** There is no equal-time offline evidence, and it adds
  reservoir state to the register-saturated shade kernel.
- **H-PLOC GPU builder.** OptiX's builder makes it moot if #2 lands. Keep it on file
  for a non-OptiX device path.

---

## 4. Roadmap

Every phase gates on the same instrument: the heavy and simple Cornell pair above,
promoted into `benchmarks/wavefront_baseline.py` by pkg298. The instrument uses GPU
burn-in and min-of-N (memory `gpu-perf-ab-clock-drift`) and runs a Cycles OptiX leg
on the same `.npy` geometry.

Every speed change must also keep images **MC-equivalent**:

- the pkg284 corpus-v2 5-seed bands stay green on CPU and GPU;
- for pure specialisation, fixed-seed images match the generic kernel to max
  |Δ| ≤ 1e-5.

| Phase | Content | Gate |
|---|---|---|
| **P0** (pkg298) | Harness + Cycles leg; BVH cache; parallel CPU build; path-pool floor | Heavy 1024² / 256 spp **≤ 32 s**, with repeat-render overhead ≤ 0.15 s at 16² / 1 spp (from 2.6 s). Heavy first-call BVH build ≤ 0.5 s. 256² throughput within 5 % of 1024² |
| **P1** (pkg299) | OptiX traversal for intersect + shadow, with triangles in hardware and spheres/curves as custom primitives or OptiX built-ins | Heavy **≤ 16 s** (≥ 2.2× vs today). Simple unchanged ±5 %. Corpus-v2 bands green on GPU. CPU untouched |
| **P2** (pkg300) | Counters profile → register-budget sweep → light/material specialisation → finer sort key | Simple **≤ 8 s** (≥ 2× vs today). Heavy **≤ 10 s**. Specialised == generic within 1e-5 |
| **P3** (parity) | Remaining shade and regen work, as P2's attribution directs | Simple ≤ 5 s and heavy ≤ 5.5 s, i.e. **Cycles OptiX parity** on both |
| **P4** (beat) | Innovation bets in §5, time-to-quality levers | Equal-time RMSE vs a 16k-spp reference **better than Cycles** on corpus v2, with raw throughput ≥ 1.2× Cycles on the simple scene |

The order is deliberate. P0 is cheap and removes a hidden tax that every viewport
geometry edit pays. P1 has the highest-confidence big win. P2 is where the largest
remaining factor is, but it starts blind until counters are enabled. P3 and P4 are
direction, not specs.

---

## 5. Innovation bets (speculative, clearly labelled)

1. **Scene-JIT shade kernels (NVRTC).** Compile the scene's actual op-VM programs and
   closure graphs to native code, with the unused lights and materials stripped out.
   Cache on disk by (feature hash, build id). Render with the generic kernel while
   compiling, as Cycles Metal does with PSO specialisation.
   - Prior art: Dr.Jit (BSD-3) and OSL-on-OptiX are the precedents.
   - Why it could beat Cycles: Cycles interprets SVM on the GPU, so a compiled closure
     graph can win outright on complex materials.
   - Risks: compile latency, possibly tens of seconds for this kernel; the `-rdc`
     link model; and NVRTC redistribution, which is covered by the CUDA EULA's
     redistributable list.
   - This is pkg300 Phase 3, gated on Phase 2 proving that specialisation pays.
2. **Wavelength-cooperative shading.** Spread one path's 4 hero wavelengths across 4
   lanes of a quad, sharing geometry through `__shfl_sync`. Per-thread spectral state
   drops about 4×, which attacks REG 254 without changing precision. It is obscure,
   and its main risk is warp-shuffle overhead. Prototype only if the P2 attribution
   shows the spectral arrays in the spill set.
3. **Blackwell hardware features after pkg299.**
   - Linear swept spheres (OptiX 9) for hair and curves, replacing the `__noinline__`
     software curve intersector.
   - Opacity micromaps for alpha-tested foliage. Astroray has no alpha in traversal
     today.
   - Cluster acceleration structures ("Mega Geometry") for 10 M+ triangle
     viewport rebuilds.
   - Evidence is NVIDIA's and vendor-reported: 5 to 20 % frame-rate gains in Alan
     Wake 2 for clusters.
4. **Shader Execution Reordering hybrid.** Run lean buckets (Lambertian, emitters) in an
   OptiX raygen "mini-megakernel" with `optixReorder(hint = material id)`, and keep
   heavy buckets on the wavefront.
   - Motivation: a wavefront pays a global-memory round trip per bounce, which SER
     avoids for cheap materials.
   - Evidence is weak so far: an arXiv 2026 photon-MC paper reports 14.7× end to end
     on an extremely divergent kernel, which does not transfer. Cycles does not use
     SER. Measure before believing.
5. **Spectral time-to-quality.** For science scenes, most of the cost is chromatic
   noise, not samples per second (pkg289 ladder).
   - Use a λ-stratified QMC dimension (pkg297) together with hero-λ proposal
     densities matched to the scene SPD (#848).
   - Expected gain is variance reduction at equal cost. No new kernel state is needed
     if the sampler supplies it.
6. **Cooperative vectors for neural materials or learned light selection (OptiX 9).**
   This puts tensor cores inside the shade stage. It is not a speed win today; watch
   only.

---

## 6. Risks

- **Parity.** The CPU oracle stays binary-SAH. OptiX triangle hits are watertight,
  while Möller-Trumbore is not, so edge hits differ at the ulp level. Gate with MC
  bands, not bit-equality (memory `ssim-wrong-gate-for-independent-rng`).
  Specialisation must be bit-equivalent to generic; any drift is a bug.
- **Register-saturated shade kernel.** pkg299 must not add live state to shade: hit
  buffers keep their layout. pkg300 is the only package allowed to restructure shade.
- **Build complexity.** OptiX adds a PTX/OptiX-IR module compile step to CMake.
  `stage_advance.cu` already takes more than 10 minutes and trips sccache (memory
  `sccache-drops-long-cuda-compiles`). OptiX modules must be separate TUs. CI has no
  GPU, so every gate is lead-run on the RTX.
- **Dependency.** The OptiX 9.1 SDK is installed at
  `C:\ProgramData\NVIDIA Corporation\OptiX SDK 9.1.0`, while `FindOptiX.cmake`
  expects 8.x. Traversal needs the SDK at build time and the driver at run time.
  Non-RTX devices keep the CUDA BVH path as the fallback.
- **Measurement.** Boost-clock drift is about 5 %, and other lanes share the GPU. Use
  burn-in, min-of-N and the lock.
- **Scope creep.** Owner direction is integration-first. P0 to P2 are perf-only and
  correctness-frozen, with no new features.

---

## 7. Sources

- Cycles kernel scheduling: https://developer.blender.org/docs/features/cycles/kernel_scheduling/ ;
  CUDA config: https://github.com/blender/cycles/blob/main/src/kernel/device/cuda/config.h (Apache-2.0).
- pbrt-v4 wavefront + OptiX traversal: https://pbr-book.org/4ed/Wavefront_Rendering_on_GPUs (code Apache-2.0).
- Laine, Karras, Aila, "Megakernels Considered Harmful", HPG 2013.
- Ylitie, Karras, Laine, "Efficient Incoherent Ray Traversal on GPUs Through Compressed Wide BVHs", HPG 2017.
- Meister et al., "On Ray Reordering Techniques for Faster GPU Ray Tracing", I3D 2020 (1.3 to 2.0× trace).
- Benthin et al., H-PLOC, HPG 2024, https://gpuopen.com/download/HPLOC.pdf .
- Wilkie et al., "Hero Wavelength Spectral Sampling", EGSR 2014.
- Jakob et al., Dr.Jit, SIGGRAPH 2022 (BSD-3).
- Pharr et al., "Filtering After Shading with Stochastic Texture Filtering", I3D 2024.
- OptiX 9.0 release (clusters, cooperative vectors, LSS): https://forums.developer.nvidia.com/t/optix-9-0-release/322842 .
- Internal: `pkg155-phase1-profile-findings.md`, `pkg174-register-pressure-ledger.md`,
  `pkg174-stage-split-design.md`, `two-level-bvh-research.md`.

## Appendix: reproduction

The scene generator writes `heavy_pos.npy` and `heavy_mid.npy`:

- two UV spheres at n = 500, displaced by `r(1 + a·sin 9θ·sin 11φ + …)`;
- the 12-triangle Cornell, with the light quad at y = 1.98 and side ±0.5.

Astroray settings: `add_triangles_bulk`, then `render(256, 8, None, False)`, camera
(0, 0, 6.8), vfov 39.6. Cycles settings:

- mesh built from the same arrays;
- diffuse and emission (strength 18) materials;
- `samples=256`, adaptive and denoise off, bounces 8.

The scratch drivers were one-offs. pkg298 folds this scene and a Cycles leg into
`benchmarks/wavefront_baseline.py`, per CLAUDE.md §5b.

## Owner decisions (2026-09-29)

- **OptiX 9.1 build dependency: approved** (pkg299). `cmake/FindOptiX.cmake` moves to 9.x.
- **OptiX default: triangles first.** Default ON for triangle-only scenes once the shadow-ray phase passes parity; spheres/curves/motion blur keep the CUDA BVH until covered.
- **CUDA 13 rebuild trial: approved** (pkg300 Phase 0).
- **Per-scene material JIT (pkg300 Phase 3): approved** to proceed after Phases 0-2.
- **Embree 4 for CPU: not approved now.**
- **Bit-identity gates (#969): use an absolute tolerance of 1e-6** instead of exact equality; no `-ffp-contract=off`.
- Owner action still needed: enable GPU performance counters once as admin (NVIDIA Control Panel > Developer), else pkg300 Phase 0 hardware counters fail with ERR_NVGPUCTRPERM.
