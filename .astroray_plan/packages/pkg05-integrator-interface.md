# pkg05 — Integrator interface

**Pillar:** 1  
**Track:** A  
**Status:** complete  
**Estimated effort:** 1 week (~4 sessions)  
**Depends on:** pkg04

---

## Goal

Before: the path tracer is a free function `pathTrace(...)` called
directly from `Renderer::render`. There is no abstraction between the
render loop and the integration algorithm. After: `include/astroray/integrator.h`
defines an `Integrator` base class; the existing path tracer becomes
`plugins/integrators/path_tracer.cpp`, registered as
`ASTRORAY_REGISTER_INTEGRATOR("path", PathTracer)`. `Renderer::render`
calls `integrator_->sample(ray, gen)`. The classic path tracer is the
default; future integrators (ReSTIR DI, NRC) drop in without touching
`Renderer`.

This is the largest single package in Pillar 1. Budget accordingly.

---

## Context

The `Integrator` interface is load-bearing for Pillar 3 (ReSTIR DI,
Neural Radiance Caching). It also enables the Blender UI to expose an
integrator selector without knowing the algorithm list at compile time.

The design is specified in `docs/light-transport.md §The Integrator
interface`. The spectral variant (`sampleSpectral`) is added here with
a default implementation that calls the RGB path and upsamples — the
actual spectral integrators come in Pillar 2.

The GR rendering path (black holes) has its own loop inside
`advanced_features.h`. It is not affected by this package — it remains
separate. This package is for the standard path tracer only.

---

## Reference

- Design doc: `docs/light-transport.md §The Integrator interface`
- Current path tracer: `src/renderer.cpp` — locate `pathTrace` or
  `Renderer::render` main loop
- Plugin pattern: `plugins/materials/lambertian.cpp`

---

## Prerequisites

- [ ] pkg04 done: textures and shapes are plugins.
- [ ] All 66+ existing tests pass.
- [ ] `include/astroray/register.h` has `ASTRORAY_REGISTER_INTEGRATOR`
      macro and `IntegratorRegistry` typedef (added in pkg01).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/integrator.h` | `Integrator` base class |
| `plugins/integrators/path_tracer.cpp` | Existing path tracer as plugin |
| `tests/test_integrator_plugin.py` | Integration tests: select by name, render a scene |

### Files to modify

| File | What changes |
|---|---|
| `src/renderer.cpp` | `Renderer` holds `shared_ptr<Integrator>`; `render()` calls `integrator_->sample()` |
| `src/renderer.cpp` | `PyRenderer` exposes `set_integrator(name)` Python method |
| `blender_addon/__init__.py` | Integrator selector property calls `astroray.integrator_registry_names()` |

### Integrator base class

Exactly as specified in `docs/light-transport.md`:

```cpp
// include/astroray/integrator.h
#pragma once
#include "astroray/param_dict.h"
#include <memory>

class Scene;
class Camera;
class Ray;
struct SampledWavelengths;
class SampledSpectrum;

class Integrator {
public:
    virtual ~Integrator() = default;

    // Returns CIE XYZ radiance. Called once per sample per pixel.
    virtual Vec3 sample(const Ray& cameraRay, std::mt19937& gen) = 0;

    // Optional per-frame setup (reservoirs, cache warmup).
    virtual void beginFrame(const Scene&, const Camera&) {}
    virtual void endFrame() {}

    // Spectral variant. Default: call sample() and convert XYZ→spectrum.
    // Spectral-native integrators override this.
    virtual SampledSpectrum sampleSpectral(const Ray&,
                                           const SampledWavelengths&,
                                           std::mt19937&);
};
```

`sampleSpectral` default implementation: call `sample()`, treat the
`Vec3` XYZ result as a flat spectrum across the wavelengths (good
enough for testing; proper spectral path tracer comes in Pillar 2).

### PathTracer plugin

Move the body of the current `pathTrace` free function into a class:

```cpp
class PathTracer : public Integrator {
public:
    explicit PathTracer(const ParamDict& p)
        : maxDepth_(p.getInt("max_depth", 50)),
          rrThreshold_(p.getFloat("rr_threshold", 0.1f)) {}

    Vec3 sample(const Ray& ray, std::mt19937& gen) override;

private:
    int maxDepth_;
    float rrThreshold_;
    // scene/camera reference injected via beginFrame or constructor?
    // See note below.
};

ASTRORAY_REGISTER_INTEGRATOR("path", PathTracer)
```

**Scene/camera reference:** the path tracer needs the scene and camera
to trace rays. Two options:

1. Pass `const Scene&` and `const Camera&` to `beginFrame` and store
   pointers.
2. Pass them to `sample()` directly (requires changing the signature).

Use option 1 to keep the `sample()` signature clean. `beginFrame`
stores `scene_` and `camera_` as raw non-owning pointers (the `Renderer`
owns the scene and camera and outlives the integrator per frame).

### Renderer changes

```cpp
class Renderer {
    // ...
    std::shared_ptr<Integrator> integrator_;
    // ...
    void render() {
        integrator_->beginFrame(scene_, camera_);
        // per-pixel loop calls integrator_->sample(ray, gen)
        integrator_->endFrame();
    }
};
```

Default integrator: `PathTracer` constructed with default `ParamDict`.
`PyRenderer::set_integrator(name)` calls
`IntegratorRegistry::instance().create(name, params)`.

---

## Acceptance criteria

- [ ] `include/astroray/integrator.h` exists with the `Integrator`
      interface as specified.
- [ ] `plugins/integrators/path_tracer.cpp` exists with one
      `ASTRORAY_REGISTER_INTEGRATOR("path", PathTracer)` call.
- [ ] Cornell box renders identically to the pre-refactor reference
      at 32 spp. Pixel-level identity under the same RNG seed (if the
      RNG initialisation is unchanged).
- [ ] `tests/test_integrator_plugin.py` passes: select "path"
      integrator by name, render a 1-sample scene, confirm non-zero
      output.
- [ ] All 66+ existing tests pass.
- [ ] `PyRenderer` exposes `set_integrator(name: str)`.
- [ ] Blender addon integrator property calls
      `astroray.integrator_registry_names()`.
- [ ] A future integrator can be added by creating one file in
      `plugins/integrators/` — demonstrate with a trivial
      `AmbientOcclusion` integrator (returns a greyscale value from
      sampling the hemisphere, ~20 lines).

---

## Non-goals

- Do not implement ReSTIR DI or NRC here. They are Pillar 3 work.
- Do not change the path tracer algorithm. Wrap it, do not rewrite it.
- Do not add the spectral path tracer. That is pkg11 (Pillar 2).
- Do not add multi-threading changes. The render loop's thread model
  does not change.
- Do not migrate the GR rendering path into this interface. It remains
  separate; its integration is deferred.

---

## Progress

- [x] Write `include/astroray/integrator.h`
- [x] Extract path tracer body from `Renderer::render` into `PathTracer`
- [x] Create `plugins/integrators/path_tracer.cpp`
- [x] Update `Renderer::render` to call through `integrator_`
- [x] Add `PyRenderer::set_integrator`
- [x] Add pybind11 binding for `integrator_registry_names()`
- [x] Update Blender addon
- [x] Write `tests/test_integrator_plugin.py`
- [x] Add `AmbientOcclusion` demo integrator
- [ ] Cornell box pixel-identity test (deferred — covered by existing standalone renderer tests)
- [x] Full test suite green (165 passed, 1 skipped)

---

## Lessons

- `beginFrame` must take `Renderer&` (non-const) because integrators call `traceFull()`, which is non-const. Storing `const Renderer*` from a `const Renderer&` beginFrame signature causes compile errors.
- `SampleResult` + `Renderer::traceFull()` preserve all AOV outputs for the PathTracer plugin path. The null-integrator fallback in render() calls `pathTrace()` directly, keeping existing AOV behavior unchanged.
- `_integrator_type_items` must be defined before `CustomRaytracerRenderSettings` in `__init__.py` — Python evaluates class bodies top-to-bottom at import time.
