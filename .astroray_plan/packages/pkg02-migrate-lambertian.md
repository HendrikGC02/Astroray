# pkg02 — Migrate Lambertian (reference migration)

**Pillar:** 1  
**Track:** A  
**Status:** done  
**Estimated effort:** 1 session (~3 h)  
**Depends on:** pkg01

---

## Goal

Before: `Lambertian` lives in `include/raytracer.h` and is
instantiated by a branch in `PyRenderer::createMaterial`. After:
`Lambertian` lives in `plugins/materials/lambertian.cpp`, registers
via `ASTRORAY_REGISTER_MATERIAL`, and `PyRenderer::createMaterial`
delegates to `MaterialRegistry::instance().create(type, params)` for
material types managed by the registry.

This package establishes the exact pattern that pkg03 will follow for
the remaining seven materials. It must be clean enough to serve as a
template.

---

## Context

The migration order in `docs/plugin-architecture.md §Migration order`
specifies materials first. Lambertian is the simplest material in the
codebase — diffuse only, two parameters (`albedo`, `roughness`). It
is the right reference case. If something is wrong with the registry
or `ParamDict` design, you want to find it here, not buried in the
Disney material.

The full pipeline validation (registry → factory → Python binding →
Blender addon) is also demonstrated here. Later migrations only need
to do the C++ side.

---

## Reference

- Design doc: `docs/plugin-architecture.md §Plugin file shape`
- `include/raytracer.h` — current `Lambertian` class definition
- `src/renderer.cpp` — current `PyRenderer::createMaterial`

---

## Prerequisites

- [ ] pkg01 is done: `include/astroray/registry.h`,
      `include/astroray/param_dict.h`, `include/astroray/register.h`
      all exist.
- [ ] `plugins/materials/` directory exists.
- [ ] All 66+ existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/materials/lambertian.cpp` | Lambertian plugin |
| `tests/test_lambertian_plugin.py` | Tests for the migrated Lambertian |

### Files to modify

| File | What changes |
|---|---|
| `src/renderer.cpp` | `PyRenderer::createMaterial` delegates to registry for "lambertian" |
| `blender_addon/__init__.py` | Material type list query changed to call registry names |

### Plugin file shape

`plugins/materials/lambertian.cpp` should look like:

```cpp
#include "astroray/register.h"
#include "raytracer.h"

class LambertianPlugin : public Material {
public:
    explicit LambertianPlugin(const ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.8f))),
          roughness_(p.getFloat("roughness", 1.0f)) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wi, const Vec3& wo)
        const override;
    BSDFSample sample(const HitRecord& rec, const Vec3& wo,
                      std::mt19937& gen) const override;
    float pdf(const HitRecord& rec, const Vec3& wi,
              const Vec3& wo) const override;

private:
    Vec3 albedo_;
    float roughness_;
};

// ... implementations (copied from existing Lambertian) ...

ASTRORAY_REGISTER_MATERIAL("lambertian", LambertianPlugin)
```

Rename the class from `Lambertian` to `LambertianPlugin` to avoid a
name clash with the existing definition during transition. Once pkg03
finishes migrating all materials, the old `Lambertian` in
`raytracer.h` can be removed.

### `PyRenderer::createMaterial` after this package

```cpp
std::shared_ptr<Material> PyRenderer::createMaterial(
    const std::string& type, const py::dict& kwargs)
{
    ParamDict p;
    for (auto& item : kwargs) {
        // ... populate ParamDict from py::dict ...
    }
    return astroray::MaterialRegistry::instance().create(type, p);
}
```

Target: under 30 lines for the full function body. The `if/else`
chain is gone for registry-managed types.

### Blender addon

`blender_addon/__init__.py` currently has a hardcoded list. Change
the material `EnumProperty` items to call the pybind11-exposed
function `astroray.material_registry_names()`. See
`docs/plugin-architecture.md §Blender addon side`.

---

## Acceptance criteria

- [ ] `plugins/materials/lambertian.cpp` exists and contains exactly
      one `ASTRORAY_REGISTER_MATERIAL("lambertian", ...)` call.
- [ ] `pytest tests/ -v` passes (66+ tests, no regressions).
- [ ] `tests/test_lambertian_plugin.py` exercises: construction from
      `ParamDict`, `eval` returns non-negative values, `sample` returns
      a direction in the upper hemisphere.
- [ ] Cornell box renders at 32 spp: compare output to
      `tests/reference/cornell_32spp.png`. Any pixel-level difference
      is a bug.
- [ ] `PyRenderer::createMaterial` is under 30 lines.
- [ ] The Blender addon EnumProperty for material type calls
      `astroray.material_registry_names()`.

---

## Non-goals

- Do not remove the old `Lambertian` definition from `raytracer.h`.
  That stays until pkg03 completes all materials so there is no
  broken intermediate state.
- Do not migrate any other material. pkg03 does the rest.
- Do not change the `Material` base class or its virtual interface.
- Do not add `evalSpectral` overloads. That is Pillar 2 work.

---

## Progress

- [x] Read current `Lambertian` in `raytracer.h`, note constructor params
- [x] Create `plugins/materials/lambertian.cpp`
- [x] Update `PyRenderer::createMaterial` in `module/blender_module.cpp`
- [x] Add `astroray.material_registry_names()` pybind11 binding
- [x] Update `blender_addon/__init__.py`
- [x] Write `tests/test_lambertian_plugin.py`
- [x] Run full test suite (120 passed, 1 skipped, 1 pre-existing failure)
- [x] Cornell box smoke test (renders OK; `tests/reference/` dir does not exist yet)

---

## Lessons

- Plugin sources must use an **OBJECT library** (not STATIC) to prevent the
  linker from dead-stripping `ASTRORAY_REGISTER_*` static initializers that
  have no direct symbol references from the main binary.
- The CMakeLists.txt `target_sources(INTERFACE … PRIVATE …)` pattern was a
  placeholder that would fail at configure time once sources existed; replaced
  with `add_library(astroray_plugins OBJECT …)` + explicit
  `target_link_libraries` on each consumer.
- The bpy.props mock in `test_blender_view_layers.py` must be updated whenever
  a new `bpy.props.*Property` is added to `blender_addon/__init__.py`.
