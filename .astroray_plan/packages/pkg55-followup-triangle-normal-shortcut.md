# pkg55-followup — Triangle normal shortcut (GPU)

**Pillar:** 1
**Track:** A
**Status:** open (low priority)
**Estimated effort:** 0.5 day
**Depends on:** pkg55-N+3 part 2 + part 2b (already merged); PR #349 (RNG+hero+harness fixes pinning the PostIntersect gate at ULP=64).
**Reference research:** PR #349's PostIntersect 32-ULP localization diagnostic in the 2026-05-23 standup §ESCALATION 1.

---

## Why this package exists

PR #349 brought CPU↔GPU PostInit from 8.7M ULP down to 2 ULP and pinned
PostIntersect at 64 ULP (32 measured + 2× headroom). The 32 ULP is clean
FMA-fusion drift across three reinforcing arithmetic sources; no single
op dominates and no algorithmic bug remains. **Pinning at 64 was the
right call.**

The diagnostic also surfaced an optional path to tighten the
PostIntersect gate further: the GPU `gpu_triangle_hit` unconditionally
computes the interpolated face normal as

```
N = (n0*w + n1*u + n2*v).normalized()    // w = 1 - u - v
```

even when `n0 == n1 == n2` (the case `scene_upload.cu:272-278` writes
when the source mesh has no per-vertex normals; that path repeats the
single face normal across all three vertex slots). Algebraically
`n0*(w+u+v) == n0` because `w+u+v == 1`, but in float arithmetic
`w+u+v != 1.0` exactly, so the multiply-add chain plus the normalize
inject extra ULP into `hit_normal`. The diagnostic measured this as the
dominant contributor to the `hit_normal.{x,y,z}` drift relative to
`hit_point.*`.

## Goal

**Before:** GPU `gpu_triangle_hit` always renormalizes an interpolated
normal. PostIntersect `hit_normal` ULP can spike to ~23 even on
flat-shaded triangles.

**After:** when the input mesh has no per-vertex normals,
`gpu_triangle_hit` returns the precomputed unit face normal directly
(no `(n0*w + n1*u + n2*v).normalized()`). PostIntersect `hit_normal` ULP
drops toward ~5; the overall PostIntersect gate can be tightened from
64 to ~16.

---

## Specification

### `src/gpu/scene_upload.cu:272-278` — flag flat-shaded triangles

Today the path stamps `n0 = n1 = n2 = face_normal` when `getVertexNormals`
returns false. Add a `flat_shaded` bool (or an `int` flag packed into a
spare bit on `GTriangle`) so the hit kernel can take a fast path.

### `include/astroray/gpu_bvh.h` — `gpu_triangle_hit` shortcut

```cpp
if (tri.flat_shaded) {
    rec.normal = tri.n0;  // already unit; same as CPU path
} else {
    rec.normal = (tri.n0 * w + tri.n1 * u + tri.n2 * v).normalized();
}
```

The CPU `Triangle::hit` (`include/astroray/shapes.h:143-176`) effectively
takes the same shortcut by using the precomputed unit `normal` field
for flat-shaded triangles; the GPU is currently doing strictly more
arithmetic than necessary.

### `tests/wavefront_diff/test_pkg55_cuda_threshold_gate.py`

After the shortcut lands and a fresh measurement on RTX, pin
`PostIntersect.max_ulp` from 64 down to whatever the new measured max is
(× 2 headroom). Likely 16 or less if the diagnostic's hypothesis holds.

---

## Acceptance criteria

- [ ] GPU triangles with flat shading take the shortcut; per-vertex-normal
      triangles still interpolate as before.
- [ ] CPU↔GPU `hit_normal` field max ULP measurably drops on the
      Cornell parity scene.
- [ ] PostIntersect overall `max_ulp` pin in `pkg55_cuda_thresholds.yaml`
      drops below 32 (likely to ~16) without any other gate regressing.

---

## Non-goals

- Do not touch the per-vertex-normal interpolation path; it's correct
  for non-flat-shaded geometry.
- Do not modify the CPU side; this is GPU-only tightening.
- Do not raise gate thresholds; only lower them.

---

## References

- PR #349 (RNG-adaptor + hero-wavelength + diff-harness fixes + initial
  PostIntersect=64 pin)
- 2026-05-23 standup §ESCALATION 1 (full diagnostic report)
- `src/gpu/scene_upload.cu:272-278` (where `flat_shaded` would be set)
- `include/astroray/gpu_bvh.h` (where `gpu_triangle_hit` does the
  redundant interpolation)
- `include/astroray/shapes.h:143-176` (CPU reference path)
