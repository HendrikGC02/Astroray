# pkg03 — Migrate remaining materials

**Pillar:** 1  
**Track:** A  
**Status:** done  
**Estimated effort:** 2 sessions (~6 h)  
**Depends on:** pkg02

---

## Goal

Before: seven materials (Metal, Dielectric, DiffuseLight, Phong,
Subsurface, Disney, NormalMapped) still live in `include/raytracer.h`
and `include/advanced_features.h`. After: all seven live under
`plugins/materials/` as individual `.cpp` files, registered via
`ASTRORAY_REGISTER_MATERIAL`. The old class definitions in the headers
are removed. `include/raytracer.h` and `include/advanced_features.h`
contain only base classes and shared types, not plugin implementations.

---

## Context

pkg02 established the pattern. This package applies it seven times.
The migrations are independent of each other and can be done
sequentially within a session. The constraint is that the build must
stay green after each material — do not migrate all seven at once and
then fix the build.

The simplest materials (Metal, Dielectric, DiffuseLight) should go
first. Disney and Subsurface are the most complex; do them last so any
issues are isolated.

---

## Reference

- Design doc: `docs/plugin-architecture.md §Migration order`
- Reference migration: `plugins/materials/lambertian.cpp` (from pkg02)
- Current definitions: `include/raytracer.h`, `include/advanced_features.h`

---

## Prerequisites

- [ ] pkg02 is done: `plugins/materials/lambertian.cpp` exists,
      `PyRenderer::createMaterial` delegates to the registry.
- [ ] All 66+ existing tests pass.

---

## Specification

### Files to create

| File | Material | Notes |
|---|---|---|
| `plugins/materials/metal.cpp` | Metal | Fuzz parameter, Schlick reflection |
| `plugins/materials/dielectric.cpp` | Dielectric | Fresnel, refraction index |
| `plugins/materials/diffuse_light.cpp` | DiffuseLight | Emissive; `eval` returns zero, `emit` returns albedo |
| `plugins/materials/phong.cpp` | Phong | Specular exponent, diffuse + specular |
| `plugins/materials/subsurface.cpp` | Subsurface | Scattering params |
| `plugins/materials/disney.cpp` | Disney | Full BSDF; largest file |
| `plugins/materials/normal_mapped.cpp` | NormalMapped | Wraps another material |
| `tests/test_material_plugins.py` | — | Energy conservation + basic output tests for all seven |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Remove plugin class bodies; keep base class `Material` and shared structs |
| `include/advanced_features.h` | Remove plugin class bodies; keep anything shared with the GR integrator |

### Migration order within the session

1. Metal — straightforward, no unusual dependencies.
2. Dielectric — uses `refract()` helper; ensure it stays in `raytracer.h`.
3. DiffuseLight — emissive; verify `emit()` virtual method is on the base class.
4. Phong — verify specular sampling is correct against the energy test.
5. Subsurface — check what scattering parameters it needs from the scene.
6. NormalMapped — this wraps another material; the inner material must
   be constructable from the registry by name, not raw pointer.
7. Disney — most complex. Read the existing implementation fully before
   touching it. Run the energy conservation test after each parameter
   change.

### NormalMapped inner material

NormalMapped takes an inner material name + params. Its `ParamDict`
spec:

```
"inner_type"   → string (e.g., "disney")
"normal_map"   → string (texture path)
+ all params for the inner material
```

Its constructor calls the registry to build the inner material:

```cpp
NormalMappedPlugin(const ParamDict& p)
    : inner_(astroray::MaterialRegistry::instance().create(
          p.getString("inner_type", "lambertian"), p)),
      normalMapPath_(p.getString("normal_map", "")) {}
```

This is the only material that calls the registry at construction time.

---

## Acceptance criteria

- [ ] Seven plugin files exist, each containing exactly one
      `ASTRORAY_REGISTER_MATERIAL` call.
- [ ] All existing tests pass (66+), including any tests that
      specifically reference Metal, Dielectric, etc.
- [ ] `tests/test_material_plugins.py` passes: energy conservation
      (reflectance ≤ 1.0 for all non-emissive materials) for each of
      the seven materials.
- [ ] Cornell box renders at 32 spp with no visual regression from
      `tests/reference/cornell_32spp.png`.
- [ ] `include/raytracer.h` no longer contains any of the seven class
      bodies (only `Material` base and shared helpers).
- [ ] `include/advanced_features.h` no longer contains material plugin
      bodies.
- [ ] A new material can be added by creating one file in
      `plugins/materials/` — demonstrate with a trivial `Mirror`
      plugin (∼10 lines: 100% specular reflection, no roughness).

---

## Non-goals

- Do not add `evalSpectral` overloads. Pillar 2 work.
- Do not modify the Disney BSDF's math. Migrate it exactly as-is.
- Do not restructure Phong into a physically-based GGX BSDF. That is
  a separate future package.
- Do not delete the `Mirror` demo plugin after adding it. Leave it as
  documentation of the pattern.

---

## Progress

- [x] Metal migrated and tested
- [x] Dielectric migrated and tested
- [x] DiffuseLight migrated and tested
- [x] Phong migrated and tested
- [x] Subsurface migrated and tested
- [x] NormalMapped migrated and tested
- [x] Disney migrated and tested
- [x] Old class bodies removed from headers
- [x] Mirror demo plugin added
- [x] Full test suite green (142 passed, 1 skipped GPU-only)

---

## Lessons

- Dynamic casts against the removed concrete classes in path tracer helpers (`isTransmissionMaterial`, `isGlossyMaterial`, `getMaterialColor`, `transparentGlass`) needed virtual dispatch on the base class before the concrete classes could be moved out. Add virtuals to Material first, then remove the class bodies.
- NormalMapped has a dual-use construction path: registry ParamDict construction and a factory function for callers that already have shared_ptr<Texture> objects (blender_module.cpp). Both are needed; the factory `makeNormalMapped` is declared in advanced_features.h and defined in the plugin .cpp.
- For alias names ("glass"/"dielectric", "light"/"emission"/"diffuse_light"), thin subclasses with `using Base::Base` avoid macro collision without duplicating any code.
- `python3` is not available on Windows; use `python`.
