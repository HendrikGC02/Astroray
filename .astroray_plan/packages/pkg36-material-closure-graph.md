# pkg36 — Shared Material Closure Graph

**Pillar:** 2/5 bridge
**Track:** A
**Status:** open
**Estimated effort:** 2-3 sessions (~9 h)
**Depends on:** pkg34, pkg35

---

## Goal

**Before:** New material plugins are ordinary C++ subclasses. That is
flexible, but CPU and GPU implementations can diverge because each novel
BSDF must be ported manually.

**After:** Common materials can declare themselves as a small graph of
known physical closures, such as diffuse, GGX conductor, dielectric
transmission, clearcoat, sheen, emission, and thin-film coating. CPU and
GPU renderers lower the same graph, so many new plugin materials work on
both backends without duplicate BSDF code.

---

## Context

The long-term ideal is plugin material breadth without backend chaos:
new materials should be easy to add, spectral by default, and consistent
between CPU and GPU. A closure graph gives that without trying to compile
arbitrary plugin C++ into CUDA.

---

## Reference

- Disney material plugin: `plugins/materials/disney.cpp`
- GPU material kernels: `include/astroray/gpu_materials.h`
- PBRT v4 BSDF layering model
- MaterialX/OSL closure concepts (inspiration only, not dependencies)

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/material_closure.h` | Closure enum, parameter payloads, and small fixed-size closure graph representation. |
| `src/material_closure.cpp` | CPU helpers and validation utilities. |
| `tests/test_material_closure_graph.py` | Registry and parity tests. |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Add optional material-to-closure-graph export. |
| `plugins/materials/*.cpp` | Export closure graphs for simple/core materials where straightforward. |
| `src/gpu/scene_upload.cu` | Lower closure graphs into GPU material records. |
| `include/astroray/gpu_materials.h` | Evaluate/sample closure graph records. |

---

## Acceptance criteria

- [ ] Lambertian, metal, flat dielectric, Disney plastic, and Disney glass
      can be represented by closure graphs.
- [ ] A new simple material plugin can be added by returning a closure
      graph without editing CUDA kernels.
- [ ] Existing hand-written material plugins still work as CPU-only escape
      hatches when no graph is provided.

---

## Non-goals

- Do not add a full OSL/MaterialX interpreter.
- Do not support runtime dynamic loading or hot reload.
