# pkg322 — Geometry Pointiness as a per-vertex attribute layer (#989 residual)

**Pillar:** 5
**Track:** A
**Status:** done (PR pending, 2026-10-06 -- per-vertex max |diff| vs Cycles 5.2 bake 1.2e-5; prod_curves_geometry CPU 0/16 -> 13/16)
**Estimated effort:** 1 session (~3 h); addon + op-VM compile; CUDA build only to confirm the GPU leg
**Depends on:** pkg310, pkg314

---

## Goal

Before: Geometry > Pointiness raises `VMCompileError` in `shader_vm_compiler._shading_input`, so any chain that reads
it is reported and flattened to a constant (prod_curves_geometry Base Color: CPU 0/16, GPU 3/16 channels in band).
After: Pointiness is computed at mesh export exactly as Cycles computes it, stored as a hidden per-corner attribute
layer on the #990 service, and the op-VM reads it like an Attribute node on CPU and GPU.

---

## Context

Owner theme 1 (complex shader nodes) and the pkg310 production node score (1/8). Pointiness is the named blocker of
prod_curves_geometry. Cycles computes it on the host at mesh sync, not in the kernel, so the port needs no new
device code and no shade-kernel state.

---

## Evidence

- 2026-10-03: pkg310 burndown, after lane at-n2: prod_curves_geometry CPU 0/16, GPU 3/16; "Pointiness (Base Color chain Noise -> RGB Curves -> Mix is reported, not evaluated)".
- 2026-10-06: `blender_addon/shader_vm_compiler.py` ~451: "Pointiness needs per-vertex curvature ... raise VMCompileError -> reported".

---

## Reference

- Cycles `intern/cycles/blender/mesh.cpp` `attr_create_pointiness` (SPDX Apache-2.0): merge colocated vertices; accumulate and normalise vertex normals; per vertex, `angle = safe_acosf(dot(normal, edge_accum / counter))`, `raw = angle * M_1_PI_F`; one blur pass over edge neighbours, `data /= counter + 1`; copy to duplicates. Cite in code.
- Attribute layers: `include/astroray/attribute_layers.h` (#990), CPU `AttributeTexture`, GPU `gpu_attrTexel`.

---

## Prerequisites

- [ ] Blender 5.2 headless for the Cycles reference.
- [ ] Main green after #1093 / #1097 / #1098 merge (shared addon file).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `blender_addon/pointiness.py` | numpy port of `attr_create_pointiness` (vertex merge, edge-angle, one blur pass) |
| `tests/test_pkg322_pointiness.py` | Per-vertex values vs a Cycles bake on three meshes (bevelled cube, dented sphere, open plane with a fold); render probe CPU + GPU |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/shader_vm_compiler.py` | `NEW_GEOMETRY` `Pointiness` compiles to an attribute read of the hidden layer instead of raising |
| `blender_addon/__init__.py` | Fill the hidden layer at mesh export only for meshes whose material reads Pointiness |
| `scripts/build/build_blender_addon.py` | Add `pointiness.py` to `ADDON_FILES` |

### Key design decisions

- **Host-side, as Cycles.** No engine or kernel change; the value rides the existing per-corner layer (Vec3, scalar in x).
- **Only when read.** Meshes whose materials do not read Pointiness pay nothing (no layer, no upload).
- **Reference values come from Cycles itself:** bake Pointiness through an Emission shader with Cycles (or read
  the Cycles attribute through a render of a flat-shaded probe), not from a re-derivation.

---

## Acceptance criteria

- [ ] Per-vertex Pointiness matches the Cycles bake within 1e-3 (max abs) on the three meshes.
- [ ] CPU and GPU render probe of a Pointiness -> ColorRamp material within the MC band of Cycles 5.2.
- [ ] prod_curves_geometry: no Pointiness DegradationReport; channels in band reported before/after, CPU and GPU.
- [ ] Scenes that do not read Pointiness render byte-identical on CPU.
- [ ] Packaged ZIP contains `pointiness.py`; `python scripts/project_index.py lint` passes.

---

## Non-goals

- Do not implement other Geometry outputs (Parametric, Random Per Island) here.
- Do not add device code or per-hit shade state.
- Do not recompute Pointiness per frame for deforming meshes beyond what export already does.

---

## Progress

- [ ] Port + unit values vs Cycles
- [ ] Compiler + export wiring
- [ ] Render probes CPU/GPU, prod_curves_geometry re-measure
- [ ] Packaging, PR

---

## Lessons

*(Fill in after the package is done.)*
