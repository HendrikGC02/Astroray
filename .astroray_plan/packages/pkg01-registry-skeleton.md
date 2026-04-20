# pkg01 — Registry skeleton

**Pillar:** 1  
**Track:** A  
**Status:** done  
**Estimated effort:** 1 session (~3 h)  
**Depends on:** none

---

## Goal

Before: no plugin infrastructure exists. New materials require editing
`raytracer.h`, `renderer.cpp`, `PyRenderer::createMaterial`, and the
Blender addon. After: `include/astroray/registry.h` exists,
`include/astroray/register.h` defines six registration macros,
`ParamDict` is a usable stringly-typed param bag, and
`plugins/materials/` exists as an empty directory. No materials
migrated yet — that is pkg02.

---

## Context

Everything downstream (pkg02 through pkg06, all Pillar 2–4 work)
requires this foundation. The registry is ~40 lines; `ParamDict` is
~60 lines. This is a single session to establish the skeleton cleanly
so all later migrations follow a consistent pattern.

See `docs/plugin-architecture.md §Design` for the exact types. This
package implements exactly what is described there — no more.

---

## Reference

- Design doc: `docs/plugin-architecture.md §Design`
- Pattern source: PBRT v4 `Registry` concept (idea only; write fresh)

---

## Prerequisites

- [ ] Build passes on `main` (run `cmake --build build -j && pytest tests/ -v`).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/registry.h` | `Registry<Product>` template |
| `include/astroray/param_dict.h` | `ParamDict` class |
| `include/astroray/register.h` | Six `ASTRORAY_REGISTER_*` macros |
| `plugins/materials/.gitkeep` | Placeholder so the directory is tracked |
| `plugins/shapes/.gitkeep` | Placeholder |
| `plugins/textures/.gitkeep` | Placeholder |
| `plugins/integrators/.gitkeep` | Placeholder |
| `plugins/passes/.gitkeep` | Placeholder |
| `tests/test_registry.py` | Unit tests for registry and ParamDict |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add `GLOB_RECURSE` for `plugins/*.cpp` to `raytracer_core` target sources |

### Key design decisions

**Registry template** — exactly as specified in
`docs/plugin-architecture.md`:

```cpp
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

**ParamDict** — variant-backed, no schema:

```cpp
class ParamDict {
    using Value = std::variant<float, int, bool, std::string, Vec3,
                               std::vector<float>>;
public:
    ParamDict& set(const std::string& key, Value v);
    float       getFloat (const std::string& key, float       dflt = 0.0f) const;
    int         getInt   (const std::string& key, int         dflt = 0)    const;
    bool        getBool  (const std::string& key, bool        dflt = false) const;
    std::string getString(const std::string& key, std::string dflt = "")   const;
    Vec3        getVec3  (const std::string& key, Vec3        dflt = {})   const;
    std::vector<float> getFloatArray(const std::string& key,
                                     std::vector<float> dflt = {}) const;
};
```

In debug builds: unknown keys on `get*` log a warning. In release
builds: silent fallback to default.

**Six macros** — one per registry category. They are near-identical;
accept the duplication per `docs/plugin-architecture.md §Registration
macro`:

```cpp
#define ASTRORAY_REGISTER_MATERIAL(name, T) \
    namespace { struct R_##T { R_##T() { \
        astroray::MaterialRegistry::instance().add(name, \
            [](const ParamDict& p) { return std::make_shared<T>(p); }); \
    }}; static R_##T _r_##T; }
```

Repeat for SHAPE, LIGHT, TEXTURE, INTEGRATOR, PASS with their
respective registry typedefs.

**Typed registry aliases** in `register.h`:

```cpp
namespace astroray {
    using MaterialRegistry   = Registry<Material>;
    using ShapeRegistry      = Registry<Hittable>;
    using TextureRegistry    = Registry<Texture>;
    using LightRegistry      = Registry<Light>;
    using IntegratorRegistry = Registry<Integrator>;
    using PassRegistry       = Registry<Pass>;
}
```

**CMakeLists.txt glob** — add after the existing `target_sources`:
```cmake
file(GLOB_RECURSE ASTRORAY_PLUGIN_SOURCES CONFIGURE_DEPENDS
     "${CMAKE_SOURCE_DIR}/plugins/*.cpp")
target_sources(raytracer_core PRIVATE ${ASTRORAY_PLUGIN_SOURCES})
```

---

## Acceptance criteria

- [ ] `include/astroray/registry.h` compiles in isolation (include
      only standard headers).
- [ ] `include/astroray/param_dict.h` compiles in isolation.
- [ ] `tests/test_registry.py` passes: register a dummy type, create
      it by name, confirm `names()` returns it.
- [ ] `ParamDict` test: set float, get back identical value; get
      unknown key returns default; setting Vec3, get Vec3 back.
- [ ] All 66+ existing tests still pass.
- [ ] `plugins/` directory tree exists with `.gitkeep` files for each
      category subdirectory.

---

## Non-goals

- Do not migrate any material. The `plugins/materials/` directory stays
  empty.
- Do not add `Integrator` or `Pass` base classes. Those come in
  pkg05/pkg06. Just the registry typedef and macro.
- Do not add Python bindings for the registry yet. Those come with
  pkg02 (prove the whole pipeline).
- Do not add schema validation, plugin metadata, or dynamic loading.

---

## Progress

- [x] Write `include/astroray/registry.h`
- [x] Write `include/astroray/param_dict.h`
- [x] Write `include/astroray/register.h`
- [x] Create `plugins/` subdirectories with `.gitkeep`
- [x] Update `CMakeLists.txt`
- [x] Write `tests/test_registry.py`
- [x] Run full test suite — 115 passed, 1 skipped (was 113+1 before pkg01)

---

## Lessons

- `raytracer_core` is INTERFACE so `target_sources(... PRIVATE ...)` is guarded by
  `if(ASTRORAY_PLUGIN_SOURCES)` — will be a no-op until pkg02 adds real `.cpp` files.
  When that happens, the library type may need revisiting.
- `Registry<T>` and `ParamDict` live in `namespace astroray`; the macros use fully
  qualified `astroray::ParamDict` to avoid requiring `using namespace astroray` at
  macro call sites.
- Forward-declare `Texture`, `Light`, `Integrator`, `Pass` in global namespace in
  `register.h` so the typed aliases compile without adding base classes yet.
