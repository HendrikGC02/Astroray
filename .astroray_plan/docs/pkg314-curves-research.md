# pkg314 / #992 — Float Curve and RGB Curves: research

Source: Blender Cycles, Apache-2.0 (SPDX `2011-2022 Blender Foundation`), branch `blender-v4.5-release`:

- `intern/cycles/kernel/svm/ramp.h` — `float_ramp_lookup`, `rgb_ramp_lookup`, `svm_node_curves`, `svm_node_curve`.
- `intern/cycles/blender/util.h` — `curvemap_minmax_curve`, `curvemapping_minmax`, `curvemapping_float_to_array`,
  `curvemapping_color_to_array`.
- `intern/cycles/blender/shader.cpp` — the `ShaderNodeRGBCurve` / `ShaderNodeVectorCurve` / `ShaderNodeFloatCurve`
  sync branches.

## Host-side table (Blender sync)

- Table length `RAMP_TABLE_SIZE + 1 = 257` entries; entry `i` samples `t = min_x + i / 256 * (max_x - min_x)`.
- `min_x` / `max_x`: minimum first-point x and maximum last-point x over the curves used (RGB Curves: 4 curves
  incl. the combined C curve; Vector Curves: 3; Float Curve: 1).
- RGB Curves compose the combined curve first: `entry.r = eval(R, eval(C, t))`, same for G and B. Vector Curves
  use `eval(X, t)`, `eval(Y, t)`, `eval(Z, t)` directly. Float Curve uses `eval(curve0, t)`.
- `extrapolate = (mapping.extend == 'EXTRAPOLATED')`. `cumap.update()` is called before evaluating.

## Kernel

- `relpos = (in - min_x) / (max_x - min_x)` per channel.
- Lookup (table size `n`): if `extrapolate` and `f < 0`: `t0 = T[0]`, `dy = t0 - T[1]`, return `t0 + dy * (-f) * (n - 1)`;
  if `extrapolate` and `f > 1`: `t0 = T[n-1]`, `dy = t0 - T[n-2]`, return `t0 + dy * (f - 1) * (n - 1)`.
  Otherwise `f = saturate(f) * (n - 1)`, `i = clamp(int(f), 0, n - 1)`, `t = f - i`, lerp `T[i]`, `T[i+1]` when `t > 0`.
- RGB / Vector Curves read channel `k` of the lookup at `relpos[k]`; result `(1 - fac) * in + fac * curve`.
- Float Curve: `(1 - fac) * in + fac * lookup(relpos)` (factor not clamped).
- Color Ramp keeps the 256-entry table with `extrapolate = false` and `[0, 1]` domain, so the same lookup reproduces
  `svm_ramp_lookup` exactly.

## Astroray port

`include/astroray/shader_graph.h` `svm_table_lookup` (one function for ramps and curves) and the `OP_CURVE` opcode;
the addon bakes the table with `CurveMapping.evaluate` exactly as `curvemapping_*_to_array` does
(`blender_addon/shader_vm_compiler.py` `_bake_curve`).
