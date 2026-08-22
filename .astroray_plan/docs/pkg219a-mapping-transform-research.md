# pkg219a — 3-D Mapping transform + coord-mode research note

**Date:** 2026-08-23
**Package:** pkg219a — Coordinate + Mapping unification (Option B: CPU + GPU parity).
**Policy:** CLAUDE.md §6 — no invented transforms. Reference = Blender/Cycles
Mapping-node semantics (Apache-2.0), borrowed not mirrored.

## Reference: Blender Mapping node (POINT type)

Cycles `intern/cycles/kernel/svm/mapping_util.h`, `svm_mapping`, POINT branch
(Apache-2.0):

```
return transform_direction(&rotationTransform, (vector * scale)) + location;
const Transform rotationTransform = euler_to_transform(rotation);
```

So the POINT mapping is:

    out = location + Rotate(euler) · (scale · vector)

Order of operations: **scale → rotate → translate**. The rotation matrix is an
XYZ-euler matrix (Blender default euler order). As a single affine matrix this is
exactly:

    M = Translate(location) · Rotate_XYZ(rotation) · Scale(scale)
    out = M · vector          (vector treated as a point / homogeneous w=1)

This is `mathutils.Matrix.LocRotScale(location, Euler(rotation, 'XYZ'), scale)`.

**Design consequence — build the matrix in the addon with `mathutils`.** Rather
than re-deriving the XYZ-euler matrix in C++/CUDA (invented-algorithm risk), the
addon composes the exact 4×4 with Blender's own `mathutils` and ships the top
3×4 (12 floats, row-major) to the engine. CPU `Texture` and the GPU
`GImageTexture` then only do the cheap affine apply `out = M·p`. This guarantees
bit-for-bit euler parity with Blender.

## Reference: Texture Coordinate node outputs

Cycles `intern/cycles/kernel/svm/tex_coord.h` (Apache-2.0). The engine `Texture`
class already implements all seven `CoordMode`s in `textureCoordinates()`
(UV / Generated / Object / Camera / Normal / Reflection / Window) — see the
pkg115 parity fixes. pkg219a only needs the **addon** to stop collapsing
Camera / Window to UV and to route them to the existing C++ modes.

## What actually ships in pkg219a

1. **Addon** (`blender_addon/__init__.py`)
   - `_resolve_vector_input`: return a full 3×4 mapping matrix (composed via
     `mathutils.Matrix.LocRotScale`, incl. X/Y rotation and Z loc/scale) instead
     of dropping to `scale_xy/offset_xy/rot_z`. Route TexCoord `Camera`/`Window`
     to their real coord modes (C++ already supports them).
   - Ship the matrix through a new binding `set_texture_mapping_matrix`.
2. **CPU `Texture`** (`include/advanced_features.h`)
   - Store an optional 3×4 mapping matrix (`hasMapping_`). When set, the sample
     coordinate is `M·p` (p = the 3-D TexCoord output); image textures sample at
     `(M·p).xy`. Legacy 2-D `setUVTransform` stays for backward compat and is
     used only when no matrix is set.
3. **GPU** (`GImageTexture` + `scene_upload.cu` + `stage_advance.cu`)
   - `GImageTexture` carries the matrix; `scene_upload.cu` copies it from the
     CPU `Texture`; the image-sample path in `shadePathSlot` applies
     `(u,v,0) → M·(u,v,0)` before `gpu_sampleImageTexture` when `hasMapping`.

## Scope guard (procedurals / pkg190)

The mapping affects the **image sampling coordinate** only. The 3-D `p` handed to
procedural `value(uv,p)` is left untransformed, so pkg190 Generated/Object voxel
bakes (`gpu_sampleProcedural3D`) are byte-identical. Procedural + non-identity
Mapping stays out of pkg219a (it already ignored the 3-D axis). GPU image
textures are always UV-sampled (triangle UVs), so the GPU apply is
`M·(u,v,0)` — the exact CPU UV-mode path.

## Register-budget plan (GPU)

The apply lands in `shadePathSlot` (called by `stageShadeBucketedKernel`,
REG:254), inside the existing `if constexpr (HasTexture)` branch — the untextured
fleet is already excluded. Matrix lives in `__constant__` (the
`GWavefrontTextureBinding` texture array), so the cost is a runtime
`if (tdesc.hasMapping)` + ~9 FMAs on already-live `uu,vv`. Probe registers with
`cuobjdump` (post-link) on the textured specializations before/after; add a
`HasTexMapping` template axis only if the textured kernels regress.

## Citations to lock in code
- Mapping matrix order: Cycles `svm/mapping_util.h` `svm_mapping` POINT
  (Apache-2.0) — `out = location + Rotate(euler)·(scale·vector)`.
- Coord modes: Cycles `svm/tex_coord.h` (Apache-2.0) — already cited in
  `advanced_features.h` per pkg115.
</content>
</invoke>
