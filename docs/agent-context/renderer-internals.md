# Renderer Internals

A technical reference for agents working on this codebase. Covers architecture,
the rendering pipeline, material conventions, and the invariants that caused
every major bug to date. Read this before touching `include/raytracer.h`.

---

## Architecture

The renderer is header-only. There is no separate compilation of the core:

```
include/raytracer.h          Core: Vec3, Ray, HitRecord, all base types,
                             BVH, Camera, Framebuffer, Renderer
include/advanced_features.h  DisneyBRDF, transforms, subsurface
include/astroray/            Plugin interfaces and GR subsystem:
  registry.h                 Registry<T> — generic factory template
  register.h                 ASTRORAY_REGISTER_* macros + type aliases
  integrator.h               Integrator base class (pkg05)
  pass.h                     Pass base class (pkg06)
  param_dict.h               Plugin parameter passing (ParamDict)
  spectral.h                 SpectralSample, SpectralWavelengths
  gr_integrator.h            GR geodesic solver (RK45/Dormand-Prince)
  metric.h / gr_types.h      Kerr metric, spacetime types
  accretion_disk.h           Novikov-Thorne disk emission
  shapes.h                   Sphere, Triangle, Mesh class bodies
apps/main.cpp                Standalone binary
module/blender_module.cpp    pybind11 binding; exposes Renderer as `astroray`
plugins/                     All plugin implementations (drop-in .cpp files):
  integrators/               path_tracer.cpp, ambient_occlusion.cpp
  materials/                 disney.cpp, lambertian.cpp, metal.cpp, …
  passes/                    oidn_denoiser.cpp, depth_aov.cpp, …
  shapes/                    sphere.cpp, triangle.cpp, black_hole.cpp, …
  textures/                  checker.cpp, noise.cpp, voronoi.cpp, …
```

Both targets (`astroray` Python module and standalone binary) compile the same
headers. The Python module is compiled with `-fPIC -fvisibility=hidden`; the
standalone binary is not. All plugins are compiled into a single OBJECT library
(`astroray_plugins`) that is linked whole into both targets — this is required
to keep the static-initialiser registration calls alive through linker
dead-stripping.

---

## Plugin System

Every extensible type (Material, Hittable/shape, Texture, Integrator, Pass)
follows the same pattern:

```cpp
// 1. include/astroray/register.h defines the registry typedef and macro
using IntegratorRegistry = Registry<Integrator>;
#define ASTRORAY_REGISTER_INTEGRATOR(name, T) \
    namespace { struct R_##T { R_##T() { \
        IntegratorRegistry::instance().add(name, \
            [](const ParamDict& p){ return make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }

// 2. A plugin file (e.g. plugins/integrators/path_tracer.cpp)
class PathTracer : public Integrator { ... };
ASTRORAY_REGISTER_INTEGRATOR("path", PathTracer)

// 3. Python / Blender selects by name
renderer.setIntegrator(IntegratorRegistry::instance().create("path", {}));
```

The same pattern applies to passes (`PassRegistry`), materials
(`MaterialRegistry`), shapes (`ShapeRegistry`), and textures (`TextureRegistry`).

**Adding a new plugin:** create one `.cpp` file in the appropriate `plugins/`
subdirectory, inherit the base class, implement the interface, and call the
registration macro. CMake's `GLOB_RECURSE` picks it up automatically on the
next `cmake -B build`.

---

## Key Types

| Type | Where | Notes |
|---|---|---|
| `Vec3` | raytracer.h:34 | Plain struct, 3 `float` members `x,y,z`. Default-constructs to (0,0,0). |
| `Ray` | raytracer.h | Constructor normalises direction. |
| `HitRecord` | raytracer.h | Set via `setFaceNormal()` — always call this from `hit()`. `isDelta` starts `false`. |
| `BSDFSample` | raytracer.h | **No default init** of `pdf` or `isDelta`. Always set every field explicitly. |
| `SampleResult` | raytracer.h | Full per-pixel result from an integrator: color, albedo, normal, depth, AOV passes. |
| `Camera` | raytracer.h | Holds all pixel buffers: `pixels`, `albedoBuffer`, `normalBuffer`, `depthBuffer`, render-pass arrays. |
| `Framebuffer` | raytracer.h | Thin named-buffer view over `Camera`. `buffer("color")` → `float*` into `cam.pixels`. Passed to `Pass::execute()`. |
| `Integrator` | astroray/integrator.h | `sample(ray, gen)` + optional `sampleFull()` for AOVs. `beginFrame`/`endFrame` for per-frame setup. |
| `Pass` | astroray/pass.h | `execute(Framebuffer&)` — post-process pass called after all tiles complete. |
| `ParamDict` | astroray/param_dict.h | Variant-based key/value store passed to plugin constructors. |

---

## Rendering Pipeline

### High-level flow (`Renderer::render`)

```
1. buildAcceleration()             — SAH BVH over scene objects
2. integrator_->beginFrame()       — per-frame integrator setup (if set)
3. #pragma omp parallel for        — tile-parallel pixel loop
   for each pixel:
     for each sample s:
       ray = camera.getRay(u, v, gen)
       if integrator_:
           result = integrator_->sampleFull(ray, gen)   // color + AOVs
       else:
           result = pathTrace(ray, depth, gen)          // fallback
       clamp firefly (lum > 20)
       accumulate color, albedo, normal, depth, passes
     average; apply filmExposure
     store to cam.pixels / cam.albedoBuffer / etc.
4. integrator_->endFrame()
5. Pass loop:
   fb = Framebuffer(cam)
   for pass in passes_:
       pass->execute(fb)            — e.g. OIDN denoiser writes to fb.buffer("color")
```

### Per-pixel accumulation detail

```
color /= samples
color *= filmExposure
alpha /= samples
passColor[i] /= samples; passColor[i] *= filmExposure  (for lighting passes)

if applyGamma:
    color = pow(clamp(color, 0, 1), 1/2.2)
else:
    color = max(color, 0)

cam.pixels[idx] = color
```

Pixels are stored **post-exposure, pre-gamma** when `applyGamma=false` (the
Python module default). The Python module applies gamma in the numpy copy step.
The standalone binary passes `applyGamma=false` to `render()` and handles gamma
itself. Do not apply gamma twice.

### `pathTrace` loop (raytracer.h ~731)

```
throughput = Vec3(1)
wasSpecular = true

for bounce in [0, maxDepth):
    if no hit:
        color += throughput * sky_background   // sky always present
        break
    if hit emissive:
        if bounce==0 or wasSpecular:           // avoid double-counting NEE
            color += throughput * emitted
        break
    if not rec.isDelta:
        color += throughput * sampleDirect()   // NEE
    Russian Roulette after bounce > 3
    bs = material.sample(rec, wo, gen)
    if bs.pdf <= 0: break
    wasSpecular = bs.isDelta
    throughput *= bs.f / (bs.pdf + 0.001f)
    if throughput.max() > 10: throughput *= 10/max
    ray = Ray(rec.point, bs.wi)
```

**Emissive double-count guard:** direct light hits are only credited when
`wasSpecular=true` or on the camera ray (bounce==0). On diffuse bounces, lights
are sampled by NEE only. Hitting a light mid-path with `wasSpecular=false` is
intentionally silently ignored.

### `sampleDirect` / NEE+MIS (raytracer.h ~703)

Two strategies combined with power heuristic:

1. **Light sampling** — sample a point on a light, shadow test, eval BSDF.
2. **BSDF sampling** — sample BSDF direction; if it hits a light, add that contribution.

`direct` returned is the full MIS estimate — **do not multiply by NdotL again**
in the caller. `eval()` already includes the cosine.

---

## Material Conventions

### `eval(rec, wo, wi)` — returns BRDF × cosine

Returns **brdf × NdotL** (cosine included).

The NEE code adds the result directly; it must not multiply by NdotL again.
The historical double-cosine bug (2026-03-15) scaled contributions as NdotL²,
causing 2× overexposure — see `docs/agent-context/lessons-learned.md`.

**Backface guard pattern** (mandatory, must come before any clamping):
```cpp
float rawNdotL = rec.normal.dot(wi);
float rawNdotV = rec.normal.dot(wo);
if (rawNdotL <= 0 || rawNdotV <= 0) return Vec3(0);
// rawNdotL / rawNdotV are now guaranteed positive — use them directly
```
Clamping before the guard makes it permanently dead. This was the root cause of
Metal's `mean=1.0` overexposure.

### `sample(rec, wo, gen)` → BSDFSample

Fields: `f` (brdf×cos), `pdf`, `isDelta`, `wi`.

- **Always initialise all fields.** `BSDFSample s;` leaves `pdf` and `isDelta`
  uninitialised.
- **`pdf` must be consistent with `eval`.** For GGX: compute D with the same
  formula and epsilon in both `eval` and `sample/pdf`. Inconsistent epsilon
  placement makes `f/pdf` diverge at low roughness.
- **Delta materials:** set `s.pdf = 1.0f`. The stochastic branch selection is
  the importance sampling — do not divide by the branch probability.

### Roughness thresholds

Metal and DisneyBRDF use a `roughness < 0.08` delta (perfect mirror) path.
Below this threshold the GGX D term is dominated by the `+0.001f` guard,
making `D/pdf ≈ 0` and the surface appear black. Threshold was raised from
0.01 to 0.08 after experimental confirmation.

---

## Pass Interface

```cpp
class Pass {
public:
    virtual void execute(Framebuffer& fb) = 0;
    virtual std::string name() const = 0;
};
```

`Framebuffer` maps string names to `float*`:

| Name | Points to | Format |
|---|---|---|
| `"color"` | `cam.pixels` | 3 floats/pixel (RGB, pre-gamma) |
| `"albedo"` | `cam.albedoBuffer` | 3 floats/pixel |
| `"normal"` | `cam.normalBuffer` | 3 floats/pixel (world space) |
| `"depth"` | `cam.depthBuffer` | 1 float/pixel |

`Vec3` is 3 consecutive floats so `reinterpret_cast<float*>(vec3_ptr)` is
safe. Passes that need OIDN or other GPU libraries guard with
`#ifdef ASTRORAY_OIDN_ENABLED` — the define is propagated to `astroray_plugins`
from CMakeLists when OIDN is found.

**Include order note:** `pass.h` must NOT include `param_dict.h` or any header
that transitively includes `raytracer.h`. `param_dict.h → raytracer.h` triggers
`Renderer::render()` to be compiled while `Pass` is still a forward declaration,
causing an incomplete-type error. Plugin `.cpp` files get `ParamDict` via
`register.h` which they always include anyway.

---

## Integrator Interface

```cpp
class Integrator {
public:
    virtual Vec3 sample(const Ray&, std::mt19937&) = 0;
    virtual SampleResult sampleFull(const Ray&, std::mt19937&);  // default: calls sample()
    virtual void beginFrame(Renderer&, const Camera&) {}
    virtual void endFrame() {}
};
```

`sampleFull` returns `SampleResult` which includes color, albedo, normal, depth,
and all render-pass AOVs. If an integrator only overrides `sample()`, AOV buffers
will be zero. `PathTracer::sampleFull` routes through `Renderer::traceFull()` to
fill all AOVs via the existing path-trace kernel.

---

## Camera and Pixel Layout

- `v = 1 - y/(height-1)` in the render loop — row 0 is the **top** of the image.
- `cam.pixels` is row-major: `pixels[y * width + x]`.
- Values are post-exposure, pre-gamma when `applyGamma=false`.
- `cam.albedoBuffer` and `cam.normalBuffer` hold first-hit AOVs (fed to OIDN).
- `Framebuffer::buffer("color")` returns `float*` into `cam.pixels.data()`.
  The OIDN denoiser reads this buffer, denoises in-place, and writes the result
  back to the same pointer — downstream gamma application in the Python binding
  then operates on the denoised data.

---

## Thread Safety

`Renderer::render()` uses `#pragma omp parallel for collapse(2)` over tiles.
Each tile gets its own `std::mt19937` seeded from `renderSeed + tileIndex`.

The progress callback is called from **inside the parallel region**. Any
non-null callback must be thread-safe. Pass `nullptr` in test code unless
explicitly using a mutex-guarded callback.

The pass loop runs **after** the parallel region finishes (single-threaded),
so passes may freely read and write Camera buffers without locking.

---

## Scene Conventions

**Cornell box** (`buildCornellBox` in `apps/main.cpp`):
- Box spans ±2 in all axes; camera at z=5.5 looking at origin.
- Light: two triangles at y=1.98, intensity 15.0.
- Three spheres: glass IOR=1.5, Disney metallic=0.5/roughness=0.3, Metal roughness=0.1.
- Expected mean pixel brightness post-gamma: ~0.38–0.42 at 64+ spp.

**Sky background** is always present: `(Vec3(1)*(1-t) + Vec3(0.5,0.7,1)*t) * 0.2f`.
Never assert "no light source = dark image" — there is always ambient sky.

---

## Debugging Brightness Problems

**Systematic overexposure (mean=1.0 or image too bright):**
1. Isolate by material: render Cornell box walls+light only, add one sphere type
   at a time. First addition that raises mean significantly is the culprit.
2. Check `eval()` backface guard — is it dead because dot products were clamped
   before the `<=0` check?
3. Check for double-cosine — does `sampleDirect` multiply by `abs(wi·normal)`
   after `eval()`? (`eval()` already includes the cosine.)
4. Check Dielectric pdf — must be 1.0, not `fresnel` or `1-fresnel`.
5. Check `f/pdf` ratio — for GGX, confirm the epsilon in pdf matches the
   epsilon in the D formula used by eval.

**Image too dark / material black:**
1. Check roughness threshold — near-mirror materials need the delta path (≥ 0.08).
2. Check `eval()` reflection direction — `2*(wo·n)*n - wo`, not `wo - 2*(wo·n)*n`.
3. Check that delta materials set `rec.isDelta = true` to suppress NEE.

**Convergence worsens with more samples:**
Positive bias per sample. Most likely: (1) dead backface guard, (2) double-cosine
in NEE, (3) Dielectric pdf = Fresnel probability instead of 1.0.

**Standalone and Python binding diverge:**
Same headers, but check default parameter values (`depth`, `adaptive`) and any
`const_cast` / mutable state that behaves differently under different
optimisation levels.
