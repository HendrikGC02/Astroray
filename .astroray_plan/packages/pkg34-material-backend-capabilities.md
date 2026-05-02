# pkg34 — Material Backend Capabilities

**Pillar:** 2/5 bridge
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg14, pkg32

---

## Goal

**Before:** CPU material plugins can be added easily, but GPU rendering
only understands a small fixed set of flattened material types. Unknown
or partially supported materials can silently become approximate GPU
materials, which makes visual diagnostics untrustworthy.

**After:** Every material declares CPU, spectral, and GPU capability
metadata. The renderer and diagnostics use GPU only when the material
lowering is known-correct for the requested scene. Unsupported material
paths fall back to CPU or report a clear diagnostic; they never silently
turn into a different material.

---

## Context

This package is the cleanup bridge between plugin breadth and GPU-default
rendering. It is also a prerequisite for serious Pillar 4 work, because
astrophysics scenes will mix spectral emitters, volumes, GR metrics, and
ordinary PBR materials. If the backend boundary is implicit, comparisons
between CPU, CUDA, and future neural/optimized paths will be confusing.

---

## Reference

- GPU upload path: `src/gpu/scene_upload.cu`
- GPU material enum: `include/astroray/gpu_types.h`
- GPU material kernels: `include/astroray/gpu_materials.h`
- Material plugin base: `include/raytracer.h`
- Visual diagnostics package: `pkg32-visual-diagnostics.md`

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Add material capability queries, e.g. `supportsGPU()`, `gpuSupportNotes()`, or a compact capability struct. |
| `src/gpu/scene_upload.cu` | Replace silent unknown-material fallback with capability-aware lowering. |
| `scripts/material_contact_sheet.py` | Use capabilities instead of a hard-coded Python allowlist. |
| `tests/` | Add backend capability and no-silent-fallback coverage. |

### Key design decisions

- Capability metadata must be cheap and declarative.
- A material may be CPU-only without being broken.
- GPU fallback may be approximate only when the material explicitly marks
  the approximation as acceptable for preview.

---

## Acceptance criteria

- [ ] Unknown material plugins do not silently render as grey Lambertian
      on GPU.
- [ ] The material contact sheet records which backend was used per tile
      and why.
- [ ] Tests cover at least one GPU-supported material, one CPU-only
      material, and one explicitly approximate preview fallback.

---

## Non-goals

- Do not implement new material physics.
- Do not make all materials GPU-native yet; pkg35 owns the spectral CUDA
  material work.
