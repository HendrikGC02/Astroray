# Cycles World / HDRI Parity Research
**pkg63** | Date: 2026-05-10 | Author: Claude Code (Sonnet 4.6)

---

## License

Blender / Cycles source is **Apache-2.0**.
Repository: `github.com/blender/blender`, `intern/cycles/`.
No code is copied verbatim; patterns referenced below are mirrored with
attribution in code comments.

---

## 1. Cycles world shader conversion

Cycles converts the entire Blender world node tree via `add_nodes()` in
`intern/cycles/blender/shader.cpp` (main branch, as of 2026-05).  Unlike
Astroray's manual node-walk, Cycles translates the full graph into its
internal shader IR.  The `ShaderNodeMapping` node is translated as:

```cpp
// intern/cycles/blender/shader.cpp
else if (b_node.is_type("ShaderNodeMapping"_ustr)) {
    MappingNode *mapping = graph->create_node<MappingNode>();
    mapping->set_mapping_type((NodeMappingType)b_node.custom1);
    node = mapping;
}
```

Rotation socket default values flow through Cycles' generic socket-value
reader (`set_default_value`).  The rotation is stored as a `float3` vector
in **XYZ Euler** order (extrinsic) matching Blender's UI — applying Rx
first, then Ry, then Rz:  `R = Rz * Ry * Rx`.

For Astroray's manual-extraction approach the equivalent is to read
`Rotation.default_value[:3]` from the Mapping node's Rotation socket and
compute the same baked 3×3 rotation matrix.

The Background node's **Color** input is another socket in the graph;
Cycles evaluates it as part of normal shader execution.  Our port reads it
via `_get_socket_color()` (which handles linked Mix/RGB nodes up to depth 8)
and stores it as a multiplicative tint applied after env-map lookup —
matching Cycles' expression: `L = env_sample * color_tint * strength`.

---

## 2. Coordinate convention

Blender world space: **Z-up** (right-handed, X-right, Y-forward, Z-up).
Astroray world space: rendered scenes use a conventional **Z-up** after
Blender export (the camera looks along −Z, Y is forward, Z is up in the
rendered world).

The existing `applyBlenderXRotation` flag applied the axis swap:
  `d_env = (d.x, d.z, −d.y)` ← maps Astroray (x,y,z) to env-map UV space.

This is equivalent to the coordinate-swap matrix:
```
R_cswap = [[1, 0, 0],
           [0, 0, 1],
           [0,-1, 0]]
```
(Astroray (x,y,z) → (x, z, −y), which then feeds the equirectangular lookup
with Y as the polar axis.)

The full baked rotation matrix for Blender convention is:
  `M = Rz(rz) * Ry(ry) * Rx(rx) * R_cswap`

For the non-Blender convention (direct callers):
  `M = Rz(rz) * Ry(ry) * Rx(rx)`

---

## 3. CDF structure — parity with Cycles

Cycles builds a conditional + marginal CDF in
`intern/cycles/scene/light.cpp → device_update_background` (main branch):

- **Conditional CDF**: per-row distribution over columns, weighted by
  luminance × sin(θ).  `cdf_width = res_x + 1`.
- **Marginal CDF**: over rows, stores row-total luminances (already weighted).
- **PDF in solid angle**: `p = (func_u × func_v) / (2π·π·sin_theta · norm_u · norm_v)`

Astroray's `buildCdf()` in `EnvironmentMap` mirrors this exactly (sin_theta
weighting, marginal/conditional two-level hierarchy, solid-angle PDF
formula).  No changes needed to the CDF builder — this is already correct.

---

## 4. XYZ Euler rotation matrix derivation

For Blender's Mapping node rotation `(rx, ry, rz)` in radians:

```
R = Rz(rz) · Ry(ry) · Rx(rx)  (XYZ extrinsic = ZYX intrinsic)

R[0] = cz·cy
R[1] = cz·sy·sx − sz·cx
R[2] = cz·sy·cx + sz·sx
R[3] = sz·cy
R[4] = sz·sy·sx + cz·cx
R[5] = sz·sy·cx − cz·sx
R[6] = −sy
R[7] = cy·sx
R[8] = cy·cx
```

After right-multiplying by R_cswap, columns 1 and 2 transform as:
`new_col1 = −old_col2`,  `new_col2 = old_col1`.

The forward transform (world → env-map lookup direction):
`d_env = M · d_world`

The inverse (env-map direction → world, used in sample()):
`d_world = Mᵀ · d_env`  (M is orthogonal so M⁻¹ = Mᵀ)

---

## 5. Color tint

Cycles formula: `L_final = envmap_lookup(dir) × background_color × strength`

Our implementation: `colorTint` stored in `EnvironmentMap` (3 floats, default
`[1,1,1]`), applied multiplicatively in `lookup()`, `evalSpectral()`, and
`sample()`.  The GPU follows the same pattern in `gpu_envmap_lookup` and
`gpu_envmap_sample`.

When the Background Color input is NOT linked, its `default_value[:3]` is
used directly.  When it IS linked, `_get_socket_color()` follows the chain
(Mix, RGB, Gamma, etc.) up to depth 8, falling back to `[1,1,1]` if
unresolvable.

---

## 6. References

- Blender/Cycles `intern/cycles/blender/shader.cpp` — world node graph
  conversion (Apache-2.0, `github.com/blender/blender`)
- Blender/Cycles `intern/cycles/scene/light.cpp` — `device_update_background`,
  CDF construction (Apache-2.0)
- Blender/Cycles `intern/cycles/kernel/light/background.h` — CDF sampling
  and PDF formula (Apache-2.0)
- Pharr, Jakob, Humphreys, *Physically Based Rendering* 4th ed. §12.6
  "Infinite Area Lights" — canonical CDF env-map sampling reference
