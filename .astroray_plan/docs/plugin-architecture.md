# Pillar 1: Plugin Architecture

**Status:** Done
**Blocks:** Pillars 2, 3, 4, 5
**Track:** A
**Duration:** 2–3 weeks

## Goal

Convert the monolithic type system into a set of small registries. New
materials, shapes, lights, textures, integrators, and passes become
files under `plugins/` that register themselves at startup.

**Not goal:** dynamic loading, hot-reload, scripting. Plugins are
compiled in via static initializers — the PBRT/Mitsuba/Cycles pattern.

## Current state

- Materials live in `include/raytracer.h` and `include/advanced_features.h`.
- Creation goes through a giant `if/else` in `PyRenderer::createMaterial`.
- Adding one material requires editing 4 files.

## Target state

- `Registry<Product>` template (~40 lines).
- Six registries: materials, shapes, lights, textures, integrators, passes.
- Each class lives in `plugins/<category>/<name>.cpp`.
- Each file ends with `ASTRORAY_REGISTER_MATERIAL("name", Class)`.
- `createMaterial` becomes
  `return MaterialRegistry::instance().create(type, params)`.

## Design

### The registry

```cpp
// include/astroray/registry.h
template <typename Product>
class Registry {
public:
    using Factory = std::function<std::shared_ptr<Product>(const ParamDict&)>;
    static Registry& instance() { static Registry r; return r; }
    void add(const std::string& name, Factory f);
    std::shared_ptr<Product> create(const std::string& name,
                                    const ParamDict& p) const;
    std::vector<std::string> names() const;
private:
    std::unordered_map<std::string, Factory> factories_;
};
```

That's the entire pattern. No inheritance diamond, no abstract factory
factory, no dynamic loading. Just a map.

### ParamDict

Simple stringly-typed bag, backed by `std::variant`:

```cpp
class ParamDict {
    using Value = std::variant<float, int, bool, std::string, Vec3,
                               std::vector<float>>;
public:
    ParamDict& set(...);
    float getFloat(const std::string& key, float dflt = 0.0f) const;
    Vec3 getVec3(const std::string& key, const Vec3& dflt = Vec3(0)) const;
    // ...
};
```

No schema, no reflection. Unknown keys log a warning in debug builds.

### Registration macro

```cpp
#define ASTRORAY_REGISTER_MATERIAL(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::MaterialRegistry::instance().add(name, \
            [](const ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }
```

Six near-identical macros (MATERIAL, SHAPE, LIGHT, TEXTURE, INTEGRATOR,
PASS). We accept the duplication for clarity over meta-macro tricks.

### Plugin file shape

`plugins/materials/disney.cpp`:

```cpp
#include "astroray/register.h"
#include "raytracer.h"

class Disney : public Material {
public:
    Disney(const ParamDict& p)
        : baseColor_(p.getVec3("base_color", Vec3(0.8f))),
          metallic_(p.getFloat("metallic", 0.0f)),
          roughness_(p.getFloat("roughness", 0.5f)) {}

    Vec3 eval(const HitRecord&, const Vec3&, const Vec3&) const override;
    BSDFSample sample(const HitRecord&, const Vec3&, std::mt19937&) const override;
    float pdf(const HitRecord&, const Vec3&, const Vec3&) const override;

private:
    Vec3 baseColor_;
    float metallic_, roughness_;
};

ASTRORAY_REGISTER_MATERIAL("disney", Disney)
```

Adding a new material = one new file. No other files change.

### Build system

```cmake
file(GLOB_RECURSE ASTRORAY_PLUGIN_SOURCES CONFIGURE_DEPENDS
     "plugins/*.cpp")
target_sources(raytracer_core PRIVATE ${ASTRORAY_PLUGIN_SOURCES})
```

The glob is the exception to the usual "globs are bad" rule. Here the
friction of hand-maintaining a list outweighs the occasional cmake
re-run.

### Blender addon side

The addon currently has an explicit list of known materials in
`__init__.py`. After this pillar it asks the registry instead:

```python
# pybind11-exposed function
material_types = astroray.material_registry_names()
# ["lambertian", "metal", "disney", ...]
```

New plugins appear in Blender automatically without addon edits.

## Migration order

**One category fully, make sure everything works, then next.** Never
parallel.

1. **Materials** (8 classes: Lambertian, Metal, Dielectric, DiffuseLight,
   Phong, Subsurface, Disney, NormalMapped). Reference migration; the
   rest follow.
2. **Textures** (9 classes: Image, Checker, Noise, Gradient, Voronoi,
   Brick, Musgrave, Magic, Wave).
3. **Shapes** (Sphere, Triangle, Mesh, ConstantMedium, BlackHole).
4. **Lights** (DiffuseLight specializations, DistantLight, SpotLight,
   AreaLight).
5. **Integrators** — extract `pathTrace`/`Renderer::render` behind an
   `Integrator` interface. Biggest single step; budget a full week.
6. **Passes** — existing pass buffer system becomes a list of `Pass`
   objects each writing to its own buffer. OIDN becomes a plugin Pass.

Packages: `pkg01` through `pkg06` in `../packages/`.

## Acceptance criteria

- [ ] All existing tests pass with migrated code (target 66+).
- [ ] A new material added by creating one file in `plugins/materials/`
      (demonstrated by a trivial `Mirror` plugin).
- [ ] `PyRenderer::createMaterial` under 30 lines.
- [ ] Blender addon picks up new materials automatically by asking the
      registry for names.
- [ ] No performance regression > 2% on Cornell box benchmark.

## Non-goals (resist these)

- **Schema validation for ParamDict.** Unknown keys log a warning.
- **Plugin metadata.** Not useful until there is a marketplace.
- **Dynamic library loading.** Drop-in-a-file is *at compile time*.
- **DI container.** You have a registry and `shared_ptr`.
- **Scripting.** Not in scope for this pillar.
