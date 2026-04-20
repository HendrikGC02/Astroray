# pkg04 — Migrate textures and shapes

**Pillar:** 1  
**Track:** A  
**Status:** open  
**Estimated effort:** 2 sessions (~6 h)  
**Depends on:** pkg03

---

## Goal

Before: nine texture classes and five shape classes (Sphere, Triangle,
Mesh, ConstantMedium, BlackHole) live in the core headers. After: all
fourteen live under `plugins/textures/` and `plugins/shapes/`
respectively, each registered via `ASTRORAY_REGISTER_TEXTURE` or
`ASTRORAY_REGISTER_SHAPE`. The old class bodies are removed from the
headers. `PyRenderer::createTexture` and `PyRenderer::createShape`
delegate to their respective registries.

---

## Context

Textures and shapes follow the same pattern as materials (pkg02/03).
The migrations are mechanical. The main complication is BlackHole —
it has dependencies on the GR integrator and must be migrated with
care not to break the existing GR rendering path.

Nine textures: Image, Checker, Noise, Gradient, Voronoi, Brick,
Musgrave, Magic, Wave.

Five shapes: Sphere, Triangle, Mesh, ConstantMedium, BlackHole.

Migrate textures first; they have no cross-dependencies. Shapes
second; BlackHole last.

---

## Reference

- Design doc: `docs/plugin-architecture.md §Migration order`
- Pattern: `plugins/materials/lambertian.cpp` (from pkg02)
- Current definitions: `include/raytracer.h`, `include/advanced_features.h`

---

## Prerequisites

- [ ] pkg03 is done: all materials are plugins, headers are clean.
- [ ] All 66+ existing tests pass.

---

## Specification

### Files to create — textures

| File | Texture class |
|---|---|
| `plugins/textures/image.cpp` | Image (loads from file path) |
| `plugins/textures/checker.cpp` | Checker (two colours, scale) |
| `plugins/textures/noise.cpp` | Noise (Perlin) |
| `plugins/textures/gradient.cpp` | Gradient (two colours, axis) |
| `plugins/textures/voronoi.cpp` | Voronoi |
| `plugins/textures/brick.cpp` | Brick |
| `plugins/textures/musgrave.cpp` | Musgrave (fBm) |
| `plugins/textures/magic.cpp` | Magic |
| `plugins/textures/wave.cpp` | Wave |
| `tests/test_texture_plugins.py` | Smoke tests: construct each texture, sample at UV (0.5, 0.5) |

### Files to create — shapes

| File | Shape class | Notes |
|---|---|---|
| `plugins/shapes/sphere.cpp` | Sphere | Centre, radius |
| `plugins/shapes/triangle.cpp` | Triangle | Three vertices + optional UV |
| `plugins/shapes/mesh.cpp` | Mesh | Loads `.obj` file; wraps triangle list |
| `plugins/shapes/constant_medium.cpp` | ConstantMedium | Volumetric; wraps another shape |
| `plugins/shapes/black_hole.cpp` | BlackHole | Wraps GR integrator; see notes |
| `tests/test_shape_plugins.py` | — | Construct + hit/miss test per shape |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Remove texture and shape class bodies |
| `include/advanced_features.h` | Remove shape class bodies |
| `src/renderer.cpp` | `createTexture` and `createShape` delegate to registry |

### BlackHole notes

BlackHole's constructor currently takes a reference to the GR
integrator or scene state. In the plugin form its `ParamDict` carries:

```
"metric"       → string (default "schwarzschild")
"mass"         → float (default 1.0)
"spin"         → float (default 0.0, for Kerr; ignored by Schwarzschild)
```

It constructs the metric from `MetricRegistry` by name. This means
the `MetricRegistry` typedef must be added to `register.h` during this
package (or in a small amendment to pkg01). If the GR metric registry
is not yet in `register.h`, add it here — it is a two-line typedef and
macro, the same as the others.

### ConstantMedium inner shape

Like NormalMapped in pkg03, `ConstantMedium` wraps another shape by
name + params:

```
"inner_type"   → string (e.g., "sphere")
"density"      → float
+ params for the inner shape
```

---

## Acceptance criteria

- [ ] Nine texture plugin files exist, each with one
      `ASTRORAY_REGISTER_TEXTURE` call.
- [ ] Five shape plugin files exist, each with one
      `ASTRORAY_REGISTER_SHAPE` call.
- [ ] `tests/test_texture_plugins.py` passes: each texture constructs
      and returns a `Vec3` from `sample(0.5, 0.5)` without crashing.
- [ ] `tests/test_shape_plugins.py` passes: sphere, triangle, mesh hit
      tests; ConstantMedium does not crash on a simple ray.
- [ ] BlackHole renders a Schwarzschild test scene (existing test scene
      if one exists) with no visual regression.
- [ ] All 66+ existing tests pass.
- [ ] `include/raytracer.h` contains no texture or shape class bodies.

---

## Non-goals

- Do not implement Kerr metric here. BlackHole only supports
  Schwarzschild in this package; Kerr is Pillar 4 (pkg30).
- Do not add procedural texture combination nodes (that is Blender's
  job, not Astroray's).
- Do not optimise Mesh with a BVH in this package. If a BVH already
  exists, preserve it; don't add one from scratch.
- Do not migrate lights. Lights are out of scope for this package.

---

## Progress

- [ ] Image texture migrated
- [ ] Checker, Noise, Gradient migrated
- [ ] Voronoi, Brick, Musgrave, Magic, Wave migrated
- [ ] Texture tests green
- [ ] Sphere, Triangle migrated
- [ ] Mesh migrated
- [ ] ConstantMedium migrated
- [ ] BlackHole migrated
- [ ] Shape tests green
- [ ] Headers cleaned
- [ ] Full test suite green

---

## Lessons

*(Fill in after done.)*
