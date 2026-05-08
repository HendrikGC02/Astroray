# pkg61 — GPU Per-Vertex Normal Interpolation (Shade Smooth Parity)

**Pillar:** 5
**Track:** A or E
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** none

---

## Goal

**Before:** "Shade Smooth" works on CPU (per-corner `split_normals` are passed via `add_triangle`) but not on GPU — meshes always render with face normals on CUDA. STATUS.md does not currently call this out, and the user reports it explicitly.

**After:** GPU triangle records carry per-vertex normals. The kernel barycentrically interpolates between them when computing shading normals. Shade Smooth output matches CPU output within Monte Carlo noise.

---

## Context

Small, isolated bug. Fixing it removes a parity difference and is a prerequisite for any "GPU is equivalent to CPU" claim.

---

## Reference

- CPU triangle add: [`renderer.add_triangle(... n0, n1, n2 ...)`](blender_addon/__init__.py:1737).
- GPU upload: `src/gpu/scene_upload.cu`.
- GPU kernel hit point math: `src/gpu/path_trace_kernel.cu`.

---

## Prerequisites

- [ ] Confirm via grep that the GPU triangle struct (`GPUTriangle` or similar in `include/astroray/gpu_types.h`) does *not* already carry per-vertex normals. If it does, this package is a no-op and we should investigate why output is wrong.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_types.h` | Add `float3 n0, n1, n2` to the GPU triangle record (or equivalent). |
| `src/gpu/scene_upload.cu` | Pass per-vertex normals when uploading. Fall back to face normal when source data is empty. |
| `src/gpu/path_trace_kernel.cu` | At hit point, if per-vertex normals are present, compute `n = normalize(b0*n0 + b1*n1 + b2*n2)` from the barycentrics. Otherwise use the face normal. |

### Files to create

| File | Purpose |
|---|---|
| `tests/test_gpu_shade_smooth.py` | Renders a sphere on CPU and GPU at fixed seed; asserts SSIM ≥ 0.97 and that the GPU image is not faceted (image variance test on a smooth-shading region). |

### Key design decisions

1. **Always-on, no flag.** Per-vertex normals carry no measurable cost in the megakernel and add only 36 bytes per triangle on the GPU side. Cheaper than gating it.
2. **Empty arrays = use face normal.** Match CPU semantics — Blender meshes without `split_normals` (rare) fall back gracefully.
3. **Don't change CPU.** This is a GPU-only fix.

---

## Acceptance criteria

- [ ] A shaded smooth sphere on GPU shows no faceting at 64 spp.
- [ ] CPU vs GPU SSIM ≥ 0.97 on the test scene.
- [ ] Existing GPU tests still pass.

---

## Non-goals

- Do not change the CPU normal interpolation.
- Do not implement custom split-normal vector data (Blender's "Custom Split Normals" feature) beyond what the per-corner array already gives us.
- Do not refactor the GPU triangle struct beyond adding three vectors.

---

## Progress

- [ ] Confirm current state of `GPUTriangle` (it may already have these fields).
- [ ] Add fields if missing.
- [ ] Update upload path.
- [ ] Update kernel interpolation.
- [ ] Test scene + parity check.

---

## Lessons

*(Fill in after the package is done.)*
