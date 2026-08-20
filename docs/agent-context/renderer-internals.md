# Renderer Internals

A technical reference for agents working on this codebase. Covers architecture,
the spectral rendering pipeline, the material/closure-graph system, the CUDA
wavefront GPU backend, and invariants that have caused real bugs. Read this
before touching `include/raytracer.h`, `include/astroray/gpu_materials.h`, or
`src/gpu/wavefront/`.

**Historical note:** an earlier (pre-spectral, ~April 2026) version of this
doc described an RGB-only architecture — `Vec3 Renderer::pathTrace()`,
`Material::eval()`/`sample()` as the light-transport contract,
`Integrator::sample()` returning `Vec3`. **That architecture is deleted.**
`Renderer::pathTrace` no longer exists. `Integrator::sample()` no longer
exists — `sampleFull()` is the sole, pure-virtual entry point.
`Material::eval()`/`sample()`/`pdf()` still exist as RGB-space virtuals but
are not the production light-transport path — see "The spectral pipeline"
below for the real contract. Do not reintroduce the old architecture.

---

## Architecture

The renderer core is still header-only C++17; CUDA device code lives under
`src/gpu/`, CPU-only wavefront/helper `.cpp` under `src/cpu/` and `src/`.

```
include/raytracer.h            Core: Vec3, Ray, HitRecord, BVH, Camera,
                                Framebuffer, Renderer::render(), spectral
                                path-trace kernels (pathTraceSpectral,
                                pathTraceSpectralCaustic)
include/advanced_features.h    DisneyBRDF helpers, transforms, subsurface
include/astroray/              Plugin interfaces, spectral types, GR subsystem,
                                GPU material/wavefront headers:
  registry.h / register.h        Registry<T> + ASTRORAY_REGISTER_* macros
  integrator.h                   Integrator base class — sampleFull() only
  pass.h / param_dict.h          Pass base class / plugin param passing
  spectrum.h                     SampledWavelengths, SampledSpectrum,
                                  RGBAlbedoSpectrum (Jakob-Hanika upsampling)
  material_closure.h             MaterialClosureGraph/Type — CPU closure desc.
  gpu_materials.h                GPU material union (GMAT_*), closure-graph
                                  lowering + eval/sample/pdf on GPU
  gpu_wavefront_state.h          GPU wavefront SoA state + launchStage*()
  gpu_renderer.h                 CUDARenderer — device upload + dispatch
  thin_film_fresnel.h/cie_table  Belcour-Barla 2017 Fresnel, CPU+GPU shared
src/cpu/wavefront/             CPU mirror of the GPU wavefront stages (used
                                for CPU/GPU parity gates)
src/gpu/wavefront/             CUDA stage kernels: stage_init, stage_intersect,
                                stage_shade_*, stage_advance, stage_restir, ...
apps/main.cpp                  Standalone binary
module/blender_module.cpp      pybind11 binding; exposes Renderer as `astroray`
plugins/                       Plugin implementations (drop-in .cpp files):
  integrators/                   path_tracer, multiwavelength_path_tracer,
                                  restir_di, neural_cache, ambient_occlusion
  materials/                     principled.cpp, disney.cpp, lambertian.cpp,
                                  metal.cpp, dielectric.cpp, thin_glass.cpp
  passes/ shapes/ textures/      oidn_denoiser.cpp, sphere.cpp, noise.cpp
blender_addon/                 Blender 5.2 RenderEngine addon (Python)
```

The plugin registry pattern (`Registry<T>`, `ASTRORAY_REGISTER_*` macros,
`plugins/*/*.cpp` files picked up by CMake `GLOB_RECURSE`) is unchanged from
the old doc — see `include/astroray/register.h`.

### Render call flow (Python binding to image)

1. Python calls `renderer.render(samples_per_pixel, max_depth, ...)`
   (`PyRenderer::render` in `module/blender_module.cpp`).
2. If `set_use_gpu(True)` was called and a CUDA device is available
   (`cudaRenderer->isAvailable()`), the call routes to the GPU wavefront
   pipeline. A CPU-only integrator (`capabilities().gpuSupported == false`)
   throws instead of silently rendering near-black (pkg171, fixing #540).
3. Otherwise it falls through to `Renderer::render()` in `include/raytracer.h`,
   which tile-parallelizes (`#pragma omp parallel for schedule(dynamic)
   collapse(2)`) over 16×16 tiles and, per pixel/sample, calls
   `integrator_->sampleFull(primaryRay, gen)`.
4. The default integrator runs the spectral path tracer via
   `Renderer::pathTraceSpectral()` / `pathTraceSpectralCaustic()`
   (`include/raytracer.h`, ~line 2380 / ~2651).
5. Per-sample color accumulates, divides by sample count, gets
   `filmExposure` applied, then gamma (`pow(clamp(c,0,1), 1/2.2)`) is applied
   **only if `applyGamma=true`** — pixels remain post-exposure, pre-gamma
   otherwise, same convention as before.
6. `Pass::execute(Framebuffer&)` runs afterward, single-threaded, over
   registered passes (OIDN, OptiX, AOV extraction).

---

## The spectral pipeline

Astroray renders in **spectral space**, not RGB. This is the single most
important structural fact for any agent touching light transport.

### Hero-wavelength sampling

- `astroray::SampledWavelengths` (`include/astroray/spectrum.h`) carries
  `kSpectrumSamples = 4` wavelengths per ray, stratified over
  `[kLambdaMin=360nm, kLambdaMax=830nm]` via `SampledWavelengths::sampleUniform()`.
- `terminateSecondary()` collapses to the hero wavelength (zeroes the other
  3 PDFs) when a bounce is wavelength-dependent (dispersion, volumetrics)
  and can't be sampled coherently across all 4.
- `astroray::SampledSpectrum` is the corresponding 4-wide radiance value.
- GR redshift is applied directly to `SampledWavelengths` (redshift factor
  `g` via `MinkowskiMetric`), not as a post-process color shift.

### Integrator contract: `sampleFull()` only

```cpp
// include/astroray/integrator.h
class Integrator {
public:
    virtual void beginFrame(Renderer&, Camera&) {}
    virtual void endFrame() {}
    virtual IntegratorCapabilities capabilities() const { return {}; }
    virtual void setMaxDepth(int depth) { (void)depth; }
    // Full-path sample: color + first-hit AOV data + render passes.
    virtual SampleResult sampleFull(const Ray& ray, std::mt19937& gen) = 0;
};
```

There is no `sample()` method and no RGB fallback. Every integrator plugin
(`plugins/integrators/*.cpp`) implements `sampleFull()` directly.
`IntegratorCapabilities::gpuSupported` declares whether a GPU kernel exists;
integrators without one must run CPU-only or the binding throws.

### Material contract: `evalSpectral()` / `sampleSpectral()`

```cpp
// include/raytracer.h, class Material
virtual astroray::SampledSpectrum evalSpectral(
        const HitRecord& rec, const Vec3& wo, const Vec3& wi,
        const astroray::SampledWavelengths& lambdas) const = 0;

virtual BSDFSampleSpectral sampleSpectral(
        const HitRecord& rec, const Vec3& wo, std::mt19937& gen,
        astroray::SampledWavelengths& lambdas) const;   // has a default impl
```

`evalSpectral()` is pure virtual — every material plugin must implement it.
`sampleSpectral()` has a default implementation that calls the legacy RGB
`sample()` and upsamples the resulting `BSDFSample::f` to spectral via
`RGBAlbedoSpectrum`; most plugins route through this default rather than
writing a bespoke spectral sampler.

`Material::eval()`/`sample()`/`pdf()` (RGB, `Vec3`-returning) **still exist**
as base-class virtuals with harmless stub defaults, and some plugins do
implement them — but only as input to the `sampleSpectral()` default's
upsampling step. They are **not** the light-transport contract:
`Renderer::pathTraceSpectral()` calls `evalSpectral()`/`sampleSpectral()`
exclusively. Do not reintroduce RGB-space `eval`/`sample` as a rendering
path — that was the pre-spectral architecture, and it is gone.

### The eta²-clamp footgun (spectral upsampling nonlinearity)

`RGBAlbedoSpectrum` (Jakob-Hanika 2019) only accepts reflectance in `[0,1]`
per channel — it clamps above 1. Glass/dielectric exit transmission carries
an `eta²` magnitude that can exceed 1 (e.g. 2.25 at IOR 1.5), so naively
upsampling `bs.f` directly clips that magnitude and darkens glass. The
default `sampleSpectral()` factors the >1 magnitude out as a flat scalar and
upsamples only the normalized `[0,1]` **tint**, reapplying the scalar after
(`include/raytracer.h` ~line 525, pkg118/#404). **Never upsample
`albedo * cosTheta / pi` or any other magnitude-bearing quantity directly**
— upsample the normalized reflectance color, carry any >1 scalar separately.
Getting this backwards caused both the GPU dielectric darkening bug (#404)
and its CPU analog (pkg118).

---

## Material system: closure-graph Principled

`include/astroray/material_closure.h` defines `MaterialClosureType` — lobes
(`Diffuse`, `GGXConductor`, `DielectricTransmission`, `Clearcoat`, `Sheen`,
`Emission`, `ThinGlass`, and `Principled` — a single monolithic closure
carrying every Principled-BSDF core-lobe parameter), `MaterialClosure`
(per-lobe weight/color/roughness/ior/...), and `MaterialClosureGraph`.

`Material::closureGraph()` is a virtual hook (default: empty). Any material
returning a non-empty, valid graph (`astroray::validateClosureGraph`) gets
`backendCapabilities().closureGraph = true` and lowers to GPU as
`GMAT_CLOSURE_GRAPH` — one generic path through `gpu_materials.h` evaluating
whatever closures the graph contains, instead of a bespoke `GMAT_*` value
per material.

`plugins/materials/principled.cpp` (`PrincipledPlugin`) is the reference
implementation: it emits exactly one `MaterialClosureType::Principled`
closure (base_color/roughness/metallic/ior/transmission/specular
tint/specular_ior_level/diffuse_roughness (EON)/thin-film thickness+IOR) and
does the CPU-side Fresnel-weighted lobe assembly directly, since
view-dependent weighting can't be baked into static per-lobe weights.
Thin-film iridescence (dielectric-coat and conductor/metallic variants)
follows Belcour & Barla 2017, shared between CPU (`thin_film_fresnel.h`) and
GPU (`gpu_thin_film_table.cuh`/`.cu`); `thin_film_cie_table.h` holds the
baked Rec.709 sensitivity LUT used on both sides.

### CPU/GPU twin relationship

`gpu_materials.h` mirrors the closure-graph/Principled system on device:
`gpu_closure_graph_eval<HasPrincipled>()`, `gpu_closure_graph_sample<...>()`,
`gpu_closure_graph_pdf<...>()` handle `GMAT_CLOSURE_GRAPH`, templated on a
`HasPrincipled` bool so non-Principled scenes don't pay the Principled
lobe's register cost (see the register-pressure constraint below — this
split exists specifically to stop Principled lobes from spilling the shared
shade kernel on scenes that don't use them). Other native GPU material
types (`GMAT_LAMBERTIAN`, `GMAT_METAL`, `GMAT_DIELECTRIC`, `GMAT_DISNEY`,
`GMAT_THIN_GLASS`, `GMAT_DIFFUSE_LIGHT`) exist for materials that don't go
through the closure graph — but plain `dielectric`/Disney glass often lowers
to `GMAT_CLOSURE_GRAPH` too. Check `Material::closureGraph()` for a given
plugin before assuming its GPU enum value.

---

## GPU wavefront pipeline

The CUDA backend (`src/gpu/wavefront/`, driven by
`include/astroray/gpu_wavefront_state.h`) is a staged wavefront path tracer
— the megakernel was removed (pkg55-C7); every GPU integrator now routes
through it. Stages, each a separate kernel launch via `launchStage*()`:

The production per-bounce scheduling is
**`stageRegen` → `stageIntersectQueued` → `stageShadeBucketed` → `stageShadow`**:

- `launchStageInit` — path/sample initialization
- `launchStageRegen` — regenerate terminated paths; also accumulates a dead
  path's radiance (accumulate-at-death XYZ conversion)
- `launchStageIntersectQueued` — BVH traversal over the live-path queue,
  bucketing hits into per-`GMaterialType` shade queues
- `launchStageShadeBucketed` — general shade kernel: material-sorted queues
  (one bucket per `GMaterialType`, fixed stride = capacity), one launch
  covers all buckets with warp-coherent material types
- `launchStageShadow` — dedicated any-hit shadow-ray stage over parked NEE samples
- `launchStageRestirPrimary` / `...InitialRIS` / `...TemporalReuse` /
  `...SpatialReuse` / `...Resolve` — ReSTIR DI reservoir stages (own kernels,
  used only by the `restir-di` integrator; no cost on the standard hot path)
- `launchStageIntersect_SessionN3` / `launchStageShadeLambertian_SessionN3` /
  `launchStageLightSample` / `launchStageRussianRoulette` /
  `launchStageShadeNeeMis` — per-stage instruments used ONLY by the CPU/GPU
  snapshot-parity test harness (`tests/wavefront_diff/`), not the render driver

(Hygiene 2026-08-11: the caller-less reference kernels from earlier sessions
— `stageAdvanceKernel`, `stageAdvanceQueuedKernel`, `stageAccumulateXYZKernel`,
`stageShadeMetalKernel` — were deleted; don't trust older docs listing them.)

### Hard constraint: register pressure

`stageShadeBucketedKernel` and `stageShadeNeeMisKernel` are **pinned at the
architectural register ceiling, REG:254** (verify via `cuobjdump` post-link — `ptxas -v` alone has
produced misleading numbers here). This is a hard constraint: any additional
per-hit live state added to these kernels spills to local memory, and
register spills in a REG:254-saturated kernel have measured as large as
+52% regression on unrelated (non-Principled) scenes. The fix pattern is
`template<bool HasPrincipled>` if-constexpr isolation — a lean and a heavy
variant of the same kernel body, dispatched by scene content — **not**
shrinking data structures across the board. Before adding a field to
per-path GPU state or a branch to a shade kernel, check register/stack usage
via `cuobjdump --dump-sass` on both variants; compiling cleanly is not
sufficient evidence.

---

## Blender addon

`blender_addon/__init__.py` is the RenderEngine integration. As of pkg178
Stage 5 it defaults to translating Blender's native **Principled BSDF**
node directly to Astroray's native `principled` material
(`_create_native_principled_material` → `renderer.create_material('principled', ...)`)
rather than decomposing it into the older Disney-BRDF parameter mapping —
controlled by `use_native_principled` (default `True`).
`_principled_native_params()` maps every Blender Principled socket onto
`plugins/materials/principled.cpp`'s param names; `_native_principled_gaps()`
reports sockets the native path doesn't yet honour (pkg119-C).

**Build:** `python scripts/build/build_blender_addon.py [--install]`. This
always passes `-DASTRORAY_DISABLE_OPENMP=ON` regardless of backend — MinGW's
`libgomp` deadlocks inside Blender's MSVC-hosted Python process. This is a
separate build tree from the `build_cuda/` test build (see
docs/DEVELOPMENT.md's "two-build story"); the addon `.pyd` and the test
build `.pyd` are not interchangeable.

Deeper Blender-parity notes and the coverage matrix live under
`docs/blender_parity/` (`report.md`, `coverage_matrix.json`,
`pkg178_stage0_closure_map.md`).

---

## Key invariants and footguns for agents

- **Seed 0 is the random sentinel, not a pin.** In `Renderer::render()`,
  `renderSeed == 0` triggers `std::random_device{}()` (non-deterministic);
  any other value seeds `std::mt19937` deterministically per-tile. A test
  passing seed 0 and expecting reproducibility is testing nothing.
- **Spectral upsampling is nonlinear in magnitude** — see the eta²-clamp
  footgun above. Upsample the reflectance color, never `albedo * cosTheta / pi`
  or anything else that can exceed 1 per channel, without factoring the >1
  scalar out first.
- **Gamma-vs-linear comparison trap.** `render()`'s `apply_gamma` defaults to
  `True` in the Python binding. Comparing a gamma-applied render against a
  linear oracle (or vice versa) produces a stable, plausible-looking
  ~1.8–2.4× "divergence" that has nothing to do with the logic under test —
  and a gamma-applied (clamped to `[0,1]`) render can never detect an
  energy-gain bug (a measured linear 4.14 reads back as a clamped 1.000).
  Energy/furnace gates must render linear (`apply_gamma=False`) and assert
  an explicit upper bound, not just a lower one.
- **CPU test suites auto-render on GPU when CUDA is available.** Hold the
  GPU lock, or otherwise verify true CPU-onlyness, before treating a "CPU"
  test run as CPU ground truth.
- **The GPU wavefront register ceiling (REG:254)** governs anything
  touching `stage_advance.cu`'s kernels — see above.
- **`Material::eval()`/`sample()`/`pdf()` are not dead code, but they are
  not where light-transport logic belongs.** They feed `sampleSpectral()`'s
  default RGB→spectral upsampling path. New materials should implement
  `evalSpectral()`/`sampleSpectral()` directly when precision matters
  (dispersion, thin-film, anything wavelength-dependent).
- **CPU can't traverse GPU instances.** The two-level BVH (TLAS/BLAS)
  instancing path has no CPU-side equivalent — it's GPU-only.

---

## Where to go next

- [docs/DEVELOPMENT.md](../DEVELOPMENT.md) — the two-build story (`build_cuda/`
  test build vs. OpenMP-free Blender addon build), perf-gate calibration,
  Windows/MinGW/CUDA footguns.
- [docs/blender_parity/](../blender_parity/) — Blender differential-parity
  coverage matrix and closure-mapping notes (pkg119, pkg178).
- [.astroray_plan/docs/STATUS.md](../../.astroray_plan/docs/STATUS.md) —
  current round status and package tracking.
- [.astroray_plan/docs/](../../.astroray_plan/docs/) — per-package research
  notes; cited algorithms (Jakob-Hanika, Belcour-Barla, Kulla-Conty, etc.)
  have derivations and reference-implementation notes here per CLAUDE.md §6.
- `docs/agent-context/lessons-learned.md` — historical bug postmortems
  (double-cosine bug, backface-guard-dead-from-clamping, etc.); still
  applicable to `evalSpectral`/`sampleSpectral` implementations, since the
  same NEE/MIS structure and cosine conventions carried over from the RGB
  era into the spectral one.
