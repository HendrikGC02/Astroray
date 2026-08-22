# pkg219c — Blender shader-node per-texel opcode semantics (op-VM reference)

Status: research reference (delegated draft, unverified until Claude review)

## Scope and conventions

This document enumerates the per-texel (non-constant-foldable) Blender shader
nodes that Astroray's pkg219 op-VM must evaluate, with the exact math each
operation performs, grounded in the Blender manual and the Cycles SVM kernel
source. It feeds pkg219b (VM core) and pkg219c (opcode fill-out).

Conventions used throughout:

- **Cycles source paths** are relative to the `blender/cycles` repository
  (mirrored at `https://github.com/blender/cycles`); the kernel files live
  under `src/kernel/svm/`. Where a file was renamed (the `svm_` prefix was
  dropped in current main), the current name is used and the legacy name is
  noted. The vendored copy in `external/cycles_light_tree/` does **not**
  contain the SVM kernel, so all kernel citations are to the upstream repo.
- **Stack model** for the proposed opcodes: a flat float stack (like the
  Cycles SVM stack, `SVM_STACK_SIZE = 255` floats, `src/kernel/svm/types.h`).
  A `vec3` occupies 3 consecutive slots. Each opcode's stack effect is given
  as `pop -> push` in float slots.
- **Sockets vs fixed parameters**: "socket" means a per-texel value that may
  be wired to another node (must be read from the stack); "fixed parameter"
  means a compile-time constant baked into the opcode's immediate data (the
  Cycles equivalent is a constant encoded in the SVM node struct, or a
  constant-folded input).
- **Cost class**: cheap = a few FLOPs, no branches; medium = branch/LUT
  (e.g. Color Ramp table lookup); view-dependent = needs the shading normal
  `N` and/or incoming direction `wi` (constrains where the VM can run).
- **Safe-math helpers** used below are defined in `src/util/math_base.h` and
  `src/util/math_float3.h`:
  - `safe_divide(a,b) = (b != 0) ? a/b : 0` (component-wise for float3)
  - `safe_sqrtf(a) = sqrt(max(a,0))`
  - `safe_powf(a,b)`: if `a < 0 && b != floor(b)` -> 0, else `powf`
  - `safe_logf(a,b) = (a <= 0 || b <= 0) ? 0 : log(a)/log(b)`
  - `safe_modulo(a,b) = (b != 0) ? fmod(a,b) : 0` (truncated remainder)
  - `safe_floored_modulo(a,b) = (b != 0) ? a - floor(a/b)*b : 0`
  - `saturatef(a) = clamp(a, 0, 1)`; `fractf(x) = x - floor(x)`
  - `interp(a,b,t) = a + t*(b-a)` (monotone mix)
  - `endvalue_preserving_mix(a,b,t) = (1-t)*a + t*b` (result == b at t == 1)
  - `wrapf(value, max, min) = value - (max-min)*floor((value-min)/(max-min))`
    (returns `min` if range == 0)
  - `pingpongf(a,b) = (b != 0) ? |fract((a-b)/(2b))*2b - b| : 0`
  - `smoothminf(a,b,k)`: if `k != 0`: `h = max(k - |a-b|, 0)/k`,
    `min(a,b) - h^3*k/6`; else `min(a,b)`
  - `compatible_signf(f) = 0 if f == 0 else +/-1`
  - `compatible_atan2(y,x) = (x == 0 && y == 0) ? 0 : atan2(y,x)`
  - `safe_normalize(a) = (len(a) != 0) ? a/len(a) : a`
  - `project(v, w) = (dot(w,w) != 0) ? (dot(v,w)/dot(w,w))*w : 0`
  - `reflect(i, n) = i - 2*n*dot(i,n)` (n pre-normalized)
  - `refract(i, n, eta)`: `k = 1 - eta^2*(1 - dot(n,i)^2)`;
    `k < 0 -> 0`, else `eta*i - (eta*dot(n,i) + sqrt(k))*n`
  - `faceforward(v, i, r) = (dot(r,i) < 0) ? v : -v`

---

## 1. Math node

- **Node name**: Math. **Cycles SVM opcode**: `NODE_MATH`
  (`src/kernel/svm/node_types_template.h`; dispatcher `svm_node_math` in
  `src/kernel/svm/math.h`; operation table `svm_math()` in
  `src/kernel/svm/math_util.h`). Operation enum `NodeMathType` in
  `src/kernel/svm/types.h`. Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/math.html
- **Inputs / outputs**: sockets `Value` (a), `Value` (b), `Value` (c) — the
  visible socket names depend on the operation (Addend/Base/Exponent/Epsilon/
  Min/Max/Increment/Scale/Degrees/Radians); output socket `Value`. The
  operation is a **fixed enum parameter** (not a socket). Cycles encodes the
  three inputs as `SVMInputFloat` (constant-or-stack-offset) and the result
  offset in `SVMNodeMath` (`src/kernel/svm/node_types.h`).
- **Exact math** (`svm_math(type, a, b, c)` in `src/kernel/svm/math_util.h`):

  | Operation (enum) | Formula |
  |---|---|
  | Add | `a + b` |
  | Subtract | `a - b` |
  | Multiply | `a * b` |
  | Divide | `safe_divide(a, b)` |
  | Multiply Add | `a * b + c` |
  | Power | `safe_powf(a, b)` |
  | Logarithm | `safe_logf(a, b)` = `(a<=0 \|\| b<=0) ? 0 : log(a)/log(b)` |
  | Square Root | `safe_sqrtf(a)` = `sqrt(max(a,0))` |
  | Inverse Square Root | `(a > 0) ? 1/sqrt(a) : 0` |
  | Absolute | `fabs(a)` |
  | Exponent | `exp(a)` |
  | Minimum | `min(a, b)` |
  | Maximum | `max(a, b)` |
  | Less Than | `(a < b) ? 1 : 0` |
  | Greater Than | `(a > b) ? 1 : 0` |
  | Sign | `compatible_signf(a)` (0 at 0, else +/-1) |
  | Compare | `((a == b) \|\| fabs(a-b) <= max(c, FLT_EPSILON)) ? 1 : 0` |
  | Smooth Minimum | `smoothminf(a, b, c)` |
  | Smooth Maximum | `-smoothminf(-a, -b, c)` |
  | Round | `floor(a + 0.5)` |
  | Floor | `floor(a)` |
  | Ceil | `ceil(a)` |
  | Truncate | `(a >= 0) ? floor(a) : ceil(a)` |
  | Fraction | `a - floor(a)` |
  | Truncated Modulo | `safe_modulo(a, b)` = `(b != 0) ? fmod(a,b) : 0` |
  | Floored Modulo | `safe_floored_modulo(a, b)` = `(b != 0) ? a - floor(a/b)*b : 0` |
  | Wrap | `wrapf(a, b, c)` — Cycles passes `(value, max, min)`; result in `[min, max]` |
  | Snap | `floor(safe_divide(a, b)) * b` |
  | Ping-pong | `pingpongf(a, b)` |
  | Sine | `sin(a)` |
  | Cosine | `cos(a)` |
  | Tangent | `tan(a)` |
  | Arcsine | `safe_asinf(a)` = `asin(clamp(a,-1,1))` |
  | Arccosine | `safe_acosf(a)` = `acos(clamp(a,-1,1))` |
  | Arctangent | `atan(a)` |
  | Arctan2 | `compatible_atan2(a, b)` |
  | Hyperbolic Sine | `sinh(a)` |
  | Hyperbolic Cosine | `cosh(a)` |
  | Hyperbolic Tangent | `tanh(a)` |
  | To Radians | `a * (pi/180)` |
  | To Degrees | `a * (180/pi)` |

  The manual's operation list matches this table (Add..To Degrees, plus the
  Clamp checkbox which is a separate output clamp, not an operation).
- **Per-texel cost class**: cheap (1-3 FLOPs) for arithmetic/comparison;
  medium for transcendentals (sin/cos/tan/exp/log/pow — a few dozen FLOPs,
  no data-dependent branches except the safe-math guards).
- **Proposed opcode**: `OP_MATH` — immediate: `op` (enum). Stack effect:
  pops 3 floats (a, b, c; unused inputs are pushed as constants by the
  compiler), pushes 1 float. A single opcode with an enum immediate mirrors
  Cycles exactly and keeps the VM small; alternatively split into
  `OP_MATH_BIN` (2-in-1-out) and `OP_MATH_UN` (1-in-1-out) to save stack
  traffic for unary ops.

---

## 2. Vector Math node

- **Node name**: Vector Math. **Cycles SVM opcode**: `NODE_VECTOR_MATH`
  (`src/kernel/svm/node_types_template.h`; dispatcher `svm_node_vector_math`
  in `src/kernel/svm/math.h`; operation table `svm_vector_math()` in
  `src/kernel/svm/math_util.h`). Enum `NodeVectorMathType` in
  `src/kernel/svm/types.h`. Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/vector_math.html
- **Inputs / outputs**: sockets `Vector` (a), `Vector` (b), `Vector` (c),
  `Scale` (float, used by Scale/Refract); outputs are dynamic — either
  `Vector` (vec3) or `Value` (float) depending on the operation. Operation is
  a **fixed enum parameter**. Cycles encodes a, b, c, param1 as
  `SVMInputFloat3`/`SVMInputFloat` and both output offsets in
  `SVMNodeVectorMath` (`src/kernel/svm/node_types.h`); the unused output
  offset is `SVM_STACK_INVALID`.
- **Exact math** (`svm_vector_math(&value, &vector, type, a, b, c, param1)`
  in `src/kernel/svm/math_util.h`; vector helpers in
  `src/util/math_float3.h`):

  | Operation (enum) | Output | Formula |
  |---|---|---|
  | Add | vec3 | `a + b` |
  | Subtract | vec3 | `a - b` |
  | Multiply | vec3 | `a * b` (component-wise) |
  | Divide | vec3 | `safe_divide(a, b)` (component-wise, 0 if divisor 0) |
  | Cross Product | vec3 | `cross(a, b)` |
  | Project | vec3 | `project(a, b)` |
  | Reflect | vec3 | `reflect(a, safe_normalize(b))` |
  | Refract | vec3 | `refract(a, safe_normalize(b), param1)` |
  | Faceforward | vec3 | `faceforward(a, b, c)` = `(dot(c,b) < 0) ? a : -a` |
  | Multiply Add | vec3 | `a * b + c` |
  | Dot Product | float | `dot(a, b)` |
  | Distance | float | `distance(a, b)` = `len(a - b)` |
  | Length | float | `len(a)` |
  | Scale | vec3 | `a * param1` |
  | Normalize | vec3 | `safe_normalize(a)` |
  | Snap | vec3 | `floor(safe_divide(a, b)) * b` |
  | Round | vec3 | `floor(a + 0.5)` |
  | Floor | vec3 | `floor(a)` |
  | Ceil | vec3 | `ceil(a)` |
  | Modulo | vec3 | `safe_fmod(a, b)` (component-wise `fmod`, 0 if divisor 0) |
  | Wrap | vec3 | `wrap(a, b, c)` (component-wise `wrapf`) |
  | Fraction | vec3 | `a - floor(a)` |
  | Absolute | vec3 | `fabs(a)` |
  | Power | vec3 | `safe_pow(a, b)` (component-wise `safe_powf`) |
  | Sign | vec3 | `compatible_sign(a)` (component-wise) |
  | Minimum | vec3 | `min(a, b)` |
  | Maximum | vec3 | `max(a, b)` |
  | Sine | vec3 | `sin(a)` |
  | Cosine | vec3 | `cos(a)` |
  | Tangent | vec3 | `tan(a)` |

  The manual's operation list matches (Add..Tangent, with Scale/Refract
  exposing the extra `Scale` socket).
- **Per-texel cost class**: cheap for arithmetic; medium for
  Normalize/Reflect/Refract/Project (sqrt/div) and the trig ops.
- **Proposed opcode**: `OP_VEC_MATH` — immediate: `op` (enum). Stack effect:
  pops 7 floats (a.xyz, b.xyz, c.xyz, param1 — unused inputs pushed as
  constants), pushes 3 floats (vec3) or 1 float (Value) depending on `op`.
  The compiler knows which output is live and can emit a variant that skips
  the dead output.

---

## 3. MixRGB / Mix node (color blend types)

- **Node name**: Mix (legacy "MixRGB" in the Color menu; the general Mix node
  with Data Type = Color). **Cycles SVM opcodes**: legacy `NODE_MIX`
  (`svm_node_mix`, factor clamped to [0,1] unconditionally) and the modern
  `NODE_MIX_COLOR` (`svm_node_mix_color`, optional factor clamp + optional
  result clamp); also `NODE_MIX_FLOAT`, `NODE_MIX_VECTOR`,
  `NODE_MIX_VECTOR_NON_UNIFORM` for the other data types
  (`src/kernel/svm/mix.h`). Blend math in `svm_mix()` and the `svm_mix_*`
  helpers in `src/kernel/svm/color_util.h`. Enum `NodeMix` in
  `src/kernel/svm/types.h`. Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/color/mix.html
- **Inputs / outputs**: sockets `Fac` (float), `Color1`/`Color2` (vec3);
  output `Color` (vec3). Blend type is a **fixed enum parameter**; `Clamp`
  factor and `Clamp Result` are fixed flags. Cycles encodes a, b, fac as
  `SVMInputFloat3`/`SVMInputFloat` plus `use_clamp`/`use_clamp_result` flags
  in `SVMNodeMixColor` (`src/kernel/svm/node_types.h`).
- **Exact math** (`svm_mix(type, t, c1, c2)` in `src/kernel/svm/color_util.h`;
  `t` is the factor, `c1` = Color1, `c2` = Color2; all ops are per-channel
  unless noted):

  | Blend type (enum) | Formula |
  |---|---|
  | Mix (BLEND) | `endvalue_preserving_mix(c1, c2, t)` = `(1-t)*c1 + t*c2` |
  | Add | `c1 + t*c2` |
  | Multiply | `c1 * ((1-t) + t*c2)` |
  | Subtract | `c1 - t*c2` |
  | Screen | `1 - ((1-t) + t*(1-c2)) * (1-c1)` |
  | Divide | per channel: `c2 != 0 ? (1-t)*c1 + t*c1/c2 : c1` |
  | Difference | `interp(c1, fabs(c1 - c2), t)` |
  | Darken | `interp(c1, min(c1, c2), t)` |
  | Lighten | `interp(c1, max(c1, c2), t)` |
  | Overlay | per channel: `c1 < 0.5 ? c1*((1-t) + 2*t*c2) : 1 - ((1-t) + 2*t*(1-c2))*(1-c1)` |
  | Dodge | per channel: if `c1 != 0`: `tmp = 1 - t*c2`; `tmp <= 0 -> 1`; else `min(c1/tmp, 1)` |
  | Burn | per channel: `tmp = (1-t) + t*c2`; `tmp <= 0 -> 0`; else `clamp(1 - (1-c1)/tmp, 0, 1)` |
  | Hue | if `sat(c2) != 0`: `hsv = rgb_to_hsv(c1)`, `hsv.x = rgb_to_hsv(c2).x`, `interp(c1, hsv_to_rgb(hsv), t)`; else `c1` |
  | Saturation | if `sat(c1) != 0`: `hsv = rgb_to_hsv(c1)`, `hsv.y = (1-t)*hsv.y + t*rgb_to_hsv(c2).y`, `hsv_to_rgb(hsv)`; else `c1` |
  | Value | `hsv = rgb_to_hsv(c1)`, `hsv.z = (1-t)*hsv.z + t*rgb_to_hsv(c2).z`, `hsv_to_rgb(hsv)` |
  | Color | if `sat(c2) != 0`: `hsv = rgb_to_hsv(c1)`, `hsv.x = hsv2.x`, `hsv.y = hsv2.y`, `interp(c1, hsv_to_rgb(hsv), t)`; else `c1` |
  | Soft Light | `scr = 1 - (1-c2)*(1-c1)`; `(1-t)*c1 + t*((1-c1)*c2*c1 + c1*scr)` |
  | Linear Light | `c1 + t*(2*c2 - 1)` |
  | Exclusion | `max(interp(c1, c1 + c2 - 2*c1*c2, t), 0)` (in Cycles enum; not in the task's minimum list) |
  | Clamp | `saturate(c1)` — used for the "Clamp" UI option, not a user-selectable blend |

  `rgb_to_hsv`/`hsv_to_rgb` are in `src/util/color.h` (standard HSV
  conversion; hue in [0,1)). Factor handling: legacy `NODE_MIX` clamps the
  factor with `saturatef` before blending (`svm_mix_clamped_factor`);
  `NODE_MIX_COLOR` clamps only if `use_clamp`, and clamps the result if
  `use_clamp_result`.
- **Per-texel cost class**: cheap for Mix/Add/Subtract/Multiply/Screen/
  Difference/Darken/Lighten/Linear Light; medium for Divide/Overlay/Dodge/
  Burn/Soft Light (branches) and Hue/Saturation/Value/Color (RGB<->HSV
  round-trip, ~30 FLOPs + branches).
- **Proposed opcode**: `OP_MIX` — immediate: `blend` (enum), `clamp_fac`
  (bool), `clamp_result` (bool). Stack effect: pops 7 floats (fac, c1.xyz,
  c2.xyz), pushes 3 floats (result.xyz). The float/vector data types of the
  modern Mix node map to `OP_MIX_F` (pops 3, pushes 1) and `OP_MIX_V`
  (pops 7, pushes 3) using `endvalue_preserving_mix`.

---

## 4. Color Ramp node

- **Node name**: Color Ramp. **Cycles SVM opcode**: `NODE_RGB_RAMP`
  (`src/kernel/svm/node_types_template.h`; `svm_node_rgb_ramp` in
  `src/kernel/svm/ramp.h`; table lookup helpers `rgb_ramp_lookup` /
  `float_ramp_lookup` in `src/kernel/svm/ramp.h` and `ramp_util.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/color_ramp.html
- **Inputs / outputs**: socket `Fac` (float); outputs `Color` (vec3) and
  `Alpha` (float). The ramp stops and the interpolation mode are **fixed
  parameters** baked into a table at graph-compile time (see below). Cycles
  encodes `table_size`, `fac`, `interpolate` flag and the two output offsets
  in `SVMNodeRGBRamp`, followed by `table_size` float4 entries (rgb + alpha)
  in the bytecode (`src/kernel/svm/node_types.h`; `RGBRampNode::compile` in
  `src/scene/shader_nodes.cpp`).
- **Exact math** (kernel side, `rgb_ramp_lookup` in `src/kernel/svm/ramp.h`):
  - `f = saturate(fac) * (table_size - 1)`
  - `i = clamp(int(f), 0, table_size - 1)`; `t = f - i`
  - `color = table[i]`; if `interpolate && t > 0`:
    `color = (1-t)*table[i] + t*table[i+1]`
  - Outputs: `Color = color.rgb`, `Alpha = color.a`. (Extrapolation is
    disabled for the Color Ramp node — `extrapolate = false`.)
  - The **interpolation modes are NOT evaluated per-texel in Cycles**: the
    Blender side bakes the ramp into a 257-entry table
    (`RAMP_TABLE_SIZE = 256`, sampled at `i/256`, `colorramp_to_array` in
    `intern/cycles/blender/util.h`; `BKE_colorband_evaluate_table_rgba` in
    `source/blender/blenkernel/intern/colorband.cc`) and the kernel only
    linearly interpolates between baked samples. The `interpolate` flag is
    set to `(ipotype != COLBAND_INTERP_CONSTANT)` (`intern/cycles/blender/
    shader.cpp`).
  - The per-stop interpolation formulas that the baking uses
    (`BKE_colorband_evaluate` in `source/blender/blenkernel/intern/
    colorband.cc`; spline weights `key_curve_position_weights` in
    `source/blender/blenkernel/intern/key.cc`), for reference if the VM
    chooses to evaluate the ramp directly instead of baking:
    - **Linear**: `out = (1-f)*c1 + f*c2` between adjacent stops.
    - **Constant**: `out = c1` (left stop; no interpolation).
    - **Ease**: `f' = 3*f^2 - 2*f^3` (smoothstep), then lerp with `f'`.
    - **Cardinal**: 4-point weighted sum with `fc = 0.71`:
      `t0 = -fc*t^3 + 2*fc*t^2 - fc*t`;
      `t1 = (2-fc)*t^3 + (fc-3)*t^2 + 1`;
      `t2 = (fc-2)*t^3 + (3-2*fc)*t^2 + fc*t`;
      `t3 = fc*t^3 - fc*t^2`;
      `out = t3*c3 + t2*c2 + t1*c1 + t0*c0` (stops c3..c0), clamped to [0,1].
    - **B-Spline**: same 4-point form with
      `t0 = -t^3/6 + t^2/2 - t/2 + 1/6`;
      `t1 = t^3/2 - t^2 + 2/3`;
      `t2 = -t^3/2 + t^2/2 + t/2 + 1/6`;
      `t3 = t^3/6`.
  - Alpha is interpolated with the same mode (the table stores rgba float4).
- **Per-texel cost class**: medium — one table lookup (index + lerp), no
  branches beyond the interpolate flag. If the VM bakes the table at compile
  time (recommended, matches Cycles bit-for-bit), per-texel cost is ~10 FLOPs.
- **Proposed opcode**: `OP_RAMP` — immediate: `table` (pointer/size),
  `interpolate` (bool). Stack effect: pops 1 float (fac), pushes 4 floats
  (color.xyz, alpha). A variant `OP_RAMP_COLOR` (push 3) / `OP_RAMP_ALPHA`
  (push 1) can be emitted when only one output is live.

---

## 5. Separate / Combine RGB, XYZ, HSV; RGB to BW

### 5a. Separate Color / Combine Color

- **Node names**: Separate Color, Combine Color. **Cycles SVM opcodes**:
  `NODE_SEPARATE_COLOR`, `NODE_COMBINE_COLOR` (`src/kernel/svm/
  sepcomb_color.h`; conversion helpers `svm_separate_color` /
  `svm_combine_color` in `src/kernel/svm/color_util.h`). Enum
  `NodeCombSepColorType` in `src/kernel/svm/types.h`. Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/separate_color.html
  and .../combine_color.html
- **Inputs / outputs**: Separate: socket `Color` (vec3), outputs `Red`/
  `Green`/`Blue` (floats). Combine: sockets `Red`/`Green`/`Blue` (floats),
  output `Color` (vec3). The color space (RGB/HSV/HSL) is a **fixed enum
  parameter**.
- **Exact math** (`src/kernel/svm/color_util.h`):
  - RGB mode: identity — `out = color` (separate) / `color = (r,g,b)`
    (combine).
  - HSV mode: `rgb_to_hsv(color)` / `hsv_to_rgb((r,g,b))` (standard HSV,
    hue in [0,1); `src/util/color.h`).
  - HSL mode: `rgb_to_hsl(color)` / `hsl_to_rgb((r,g,b))` (`src/util/
    color.h`).
- **Per-texel cost class**: cheap for RGB; medium for HSV/HSL (branchy
  conversion, ~30 FLOPs).
- **Proposed opcode**: `OP_SEP_COLOR` — immediate: `space` (enum). Stack
  effect: pops 3 floats (color.xyz), pushes 3 floats (r,g,b). `OP_COMBINE_COLOR`
  — immediate: `space` (enum). Pops 3, pushes 3. (The VM can emit only the
  live output components; Cycles emits one node per output component for the
  vector variant, see 5b.)

### 5b. Separate XYZ / Combine XYZ

- **Node names**: Separate XYZ, Combine XYZ. **Cycles SVM opcodes**:
  `NODE_SEPARATE_VECTOR`, `NODE_COMBINE_VECTOR` (`src/kernel/svm/
  sepcomb_vector.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/separate_xyz.html
  and .../combine_xyz.html
- **Inputs / outputs**: Separate: socket `Vector` (vec3), one float output
  (X/Y/Z). Combine: one float input (X/Y/Z), output `Vector` (vec3). Cycles
  emits **one node instance per component** (`vector_index` 0/1/2 in
  `SVMNodeSeparateVector`/`SVMNodeCombineVector`, `src/kernel/svm/
  node_types.h`).
- **Exact math**: component extraction / insertion — `out = v[i]` /
  `v[i] = in`. No conversion.
- **Per-texel cost class**: cheap (1 FLOP / a store).
- **Proposed opcode**: `OP_SEP_VEC` — immediate: `index` (0/1/2). Pops 3,
  pushes 1. `OP_COMBINE_VEC` — immediate: `index` (0/1/2). Pops 1, pushes 3
  (the other two components are taken from the stack as pre-existing values,
  or the compiler emits a 3-input combine when all components are live).

### 5c. RGB to BW

- **Node name**: RGB to BW. **Cycles SVM opcode**: `NODE_CONVERT` with
  `NODE_CONVERT_CF` (color->float) (`src/kernel/svm/convert.h`; luma helper
  `linear_rgb_to_gray` in `src/kernel/util/colorspace.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/rgb_to_bw.html
- **Inputs / outputs**: socket `Color` (vec3), output `Val` (float).
- **Exact math**: `linear_rgb_to_gray(kg, c) = dot(c, rgb_to_y)` where
  `rgb_to_y` is the Rec.709 luma vector (0.2126, 0.7152, 0.0722) in the
  default working color space (`src/kernel/util/colorspace.h`).
- **Per-texel cost class**: cheap (3 mults + 2 adds).
- **Proposed opcode**: `OP_RGB_TO_BW` — immediate: `luma` (vec3 constant).
  Pops 3, pushes 1.

---

## 6. Invert, Gamma, Bright/Contrast

### 6a. Invert

- **Node name**: Invert. **Cycles SVM opcode**: `NODE_INVERT`
  (`src/kernel/svm/invert.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/color/invert.html
- **Inputs / outputs**: sockets `Fac` (float), `Color` (vec3); output
  `Color` (vec3).
- **Exact math** (`invert(color, factor)` in `src/kernel/svm/invert.h`,
  per channel): `out = fac*(1 - c) + (1 - fac)*c`.
- **Per-texel cost class**: cheap (3 FLOPs/channel).
- **Proposed opcode**: `OP_INVERT` — pops 4 floats (fac, c.xyz), pushes 3.

### 6b. Gamma

- **Node name**: Gamma. **Cycles SVM opcode**: `NODE_GAMMA`
  (`src/kernel/svm/gamma.h`; `svm_math_gamma_color` in
  `src/kernel/svm/math_util.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/color/gamma.html
- **Inputs / outputs**: sockets `Color` (vec3), `Gamma` (float); output
  `Color` (vec3).
- **Exact math** (`svm_math_gamma_color` in `src/kernel/svm/math_util.h`,
  per channel): if `gamma == 0` -> `1`; else if `c > 0` -> `pow(c, gamma)`;
  channels <= 0 are left unchanged.
- **Per-texel cost class**: medium (pow per channel).
- **Proposed opcode**: `OP_GAMMA` — pops 4 floats (c.xyz, gamma), pushes 3.

### 6c. Bright/Contrast

- **Node name**: Bright/Contrast. **Cycles SVM opcode**: `NODE_BRIGHTCONTRAST`
  (`src/kernel/svm/brightness.h`; `svm_brightness_contrast` in
  `src/kernel/svm/color_util.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/color/bright_contrast.html
- **Inputs / outputs**: sockets `Color` (vec3), `Bright` (float),
  `Contrast` (float); output `Color` (vec3).
- **Exact math** (`svm_brightness_contrast` in `src/kernel/svm/color_util.h`,
  per channel): `a = 1 + contrast`; `b = brightness - contrast*0.5`;
  `out = max(a*c + b, 0)`.
- **Per-texel cost class**: cheap (4 FLOPs/channel).
- **Proposed opcode**: `OP_BRIGHT_CONTRAST` — pops 5 floats (c.xyz, bright,
  contrast), pushes 3.

---

## 7. Hue/Saturation/Value node

- **Node name**: Hue/Saturation/Value. **Cycles SVM opcode**: `NODE_HSV`
  (`src/kernel/svm/hsv.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/color/hue_saturation_value.html
- **Inputs / outputs**: sockets `Hue` (float), `Saturation` (float),
  `Value` (float), `Fac` (float), `Color` (vec3); output `Color` (vec3).
- **Exact math** (`svm_node_hsv` in `src/kernel/svm/hsv.h`):
  1. `hsv = rgb_to_hsv(color)`
  2. `hsv.x = fract(hsv.x + hue + 0.5)` (hue offset, wrapped to [0,1))
  3. `hsv.y = saturate(hsv.y * sat)`
  4. `hsv.z = hsv.z * val`
  5. `tmp = hsv_to_rgb(hsv)`
  6. `out = fac*tmp + (1-fac)*color` (per channel)
  7. `out = max(out, 0)` (clamp negatives from over-saturation)
- **Per-texel cost class**: medium (two RGB<->HSV round-trips + branches).
- **Proposed opcode**: `OP_HSV` — pops 7 floats (hue, sat, val, fac,
  color.xyz), pushes 3.

---

## 8. Map Range and Clamp nodes

### 8a. Map Range

- **Node name**: Map Range. **Cycles SVM opcodes**: `NODE_MAP_RANGE`
  (scalar) and `NODE_VECTOR_MAP_RANGE` (vector) (`src/kernel/svm/
  map_range.h`). Enum `NodeMapRangeType` in `src/kernel/svm/types.h`.
  Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/map_range.html
- **Inputs / outputs**: scalar: sockets `Value`, `From Min`, `From Max`,
  `To Min`, `To Max`, `Steps` (floats); output `Result` (float). Vector:
  same sockets as vec3. Interpolation type is a **fixed enum parameter**
  (Linear/Stepped/Smoothstep/Smootherstep); `Clamp` is a fixed flag (scalar
  node clamps only in the vector variant; the scalar node has no clamp flag
  in Cycles — the manual's "Clamp" applies to the vector node).
- **Exact math** (`svm_node_map_range` in `src/kernel/svm/map_range.h`):
  - If `from_max == from_min`: `result = 0` (scalar) / `factor = 0` (vector).
  - **Linear**: `factor = (value - from_min) / (from_max - from_min)`.
  - **Stepped**: `factor = (value - from_min) / (from_max - from_min)`;
    `factor = (steps > 0) ? floor(factor * (steps + 1)) / steps : 0`.
  - **Smoothstep**: scalar:
    `factor = (from_min > from_max) ? 1 - smoothstep(from_max, from_min, value)
    : smoothstep(from_min, from_max, value)` where
    `smoothstep(e0, e1, x) = clamp((x - e0)/(e1 - e0), 0, 1)` then
    `3*f^2 - 2*f^3`. Vector: `factor = clamp((value - from_min)/
    (from_max - from_min), 0, 1)` then `(3 - 2*factor) * factor^2`.
  - **Smootherstep**: same but `f^3 * (f*(6f - 15) + 10)`.
  - Final: `result = to_min + factor * (to_max - to_min)`.
  - Vector clamp (if `use_clamp` and type is Linear/Stepped):
    `result = clamp(result, min(to_min, to_max), max(to_min, to_max))`
    per channel. Smoothstep/Smootherstep ignore `use_clamp` (already in
    [0,1]).
- **Per-texel cost class**: cheap for Linear/Stepped; medium for
  Smoothstep/Smootherstep (pow/div).
- **Proposed opcode**: `OP_MAP_RANGE` — immediate: `type` (enum),
  `use_clamp` (bool). Pops 6 floats (value, from_min, from_max, to_min,
  to_max, steps), pushes 1. `OP_MAP_RANGE_V` — same, pops 18, pushes 3.

### 8b. Clamp

- **Node name**: Clamp. **Cycles SVM opcode**: `NODE_CLAMP`
  (`src/kernel/svm/clamp.h`). Enum `NodeClampType` in `src/kernel/svm/
  types.h`. Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/clamp.html
- **Inputs / outputs**: sockets `Value`, `Min`, `Max` (floats); output
  `Result` (float). Clamp type (Min Max / Range) is a **fixed enum
  parameter**.
- **Exact math** (`svm_node_clamp` in `src/kernel/svm/clamp.h`):
  - Min Max: `clamp(value, min, max)`.
  - Range: if `min > max`: `clamp(value, max, min)`; else
    `clamp(value, min, max)`.
- **Per-texel cost class**: cheap.
- **Proposed opcode**: `OP_CLAMP` — immediate: `type` (enum). Pops 3,
  pushes 1.

---

## 9. Value and RGB nodes (constant sources)

- **Node names**: Value, RGB. **Cycles SVM opcodes**: `NODE_VALUE_F`
  (float constant) and `NODE_VALUE_V` (vec3 constant) (`src/kernel/svm/
  value.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/input/value.html
  and .../input/rgb.html
- **Inputs / outputs**: no sockets; the value is a **fixed parameter**
  (`SVMNodeValueF.value` / `SVMNodeValueV.value`, `src/kernel/svm/
  node_types.h`). Outputs: `Value` (float) / `Color` (vec3).
- **Exact math**: push the constant. These nodes are constant-foldable on
  their own, but they appear as *inputs* to per-texel ops, so the VM needs a
  way to push constants onto the stack.
- **Per-texel cost class**: cheap (immediate load).
- **Proposed opcode**: `OP_CONST_F` — immediate: `value` (float). Pops 0,
  pushes 1. `OP_CONST_V3` — immediate: `value` (vec3). Pops 0, pushes 3.
  (The compiler may instead fold constants into the consuming opcode's
  immediate data, as Cycles does with `SVMInputFloat`.)

---

## 10. Fresnel and Layer Weight nodes (VIEW-DEPENDENT)

> These two nodes read the shading normal `N` and the incoming direction
> `wi` from the `ShaderData`. They **cannot** be evaluated in a texture-only
> pre-pass; see the design constraint in the summary section.

### 10a. Fresnel

- **Node name**: Fresnel. **Cycles SVM opcode**: `NODE_FRESNEL`
  (`src/kernel/svm/fresnel.h`; `fresnel_dielectric_cos` in
  `src/kernel/closure/bsdf_util.h`). Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/input/fresnel.html
- **Inputs / outputs**: sockets `IOR` (float), `Normal` (vec3, defaults to
  `sd->N`); output `Fac` (float).
- **Exact math** (`svm_node_fresnel` in `src/kernel/svm/fresnel.h`):
  - `eta = max(ior, 1e-5)`; if backfacing: `eta = 1/eta`
  - `f = fresnel_dielectric_cos(dot(wi, N), eta)` where
    `fresnel_dielectric_cos(cosi, eta)` (`src/kernel/closure/bsdf_util.h`):
    `c = |cosi|`; `g = eta^2 - 1 + c^2`; if `g > 0`:
    `g = sqrt(g)`; `A = (g - c)/(g + c)`; `B = (c*(g + c) - 1)/(c*(g - c) + 1)`;
    `f = 0.5 * A^2 * (1 + B^2)`; else (total internal reflection) `f = 1`.
- **Per-texel cost class**: view-dependent (needs `wi` and `N`); medium
  (sqrt + a few FLOPs).
- **Proposed opcode**: `OP_FRESNEL` — immediate: `normal_slot` (stack slot
  or default-N flag). Pops 4 floats (ior, normal.xyz), pushes 1. Must run in
  a context that provides `wi` and `N`.

### 10b. Layer Weight

- **Node name**: Layer Weight. **Cycles SVM opcode**: `NODE_LAYER_WEIGHT`
  (`src/kernel/svm/fresnel.h`). Enum `NodeBlendWeightType` in
  `src/kernel/svm/types.h`. Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/input/layer_weight.html
- **Inputs / outputs**: sockets `Blend` (float), `Normal` (vec3, defaults to
  `sd->N`); outputs `Fresnel` (float) and `Facing` (float). The output
  selection is a **fixed enum parameter** (`NODE_LAYER_WEIGHT_FRESNEL` /
  `NODE_LAYER_WEIGHT_FACING`).
- **Exact math** (`svm_node_layer_weight` in `src/kernel/svm/fresnel.h`):
  - **Fresnel**: `eta = max(1 - blend, 1e-5)`; if backfacing: `eta = eta`
    else `eta = 1/eta`; `f = fresnel_dielectric_cos(dot(wi, N), eta)`.
  - **Facing**: `f = |dot(wi, N)|`; if `blend != 0.5`:
    `blend = clamp(blend, 0, 1 - 1e-5)`;
    `blend = (blend < 0.5) ? 2*blend : 0.5/(1 - blend)`;
    `f = pow(f, blend)`; then `f = 1 - f`.
- **Per-texel cost class**: view-dependent (needs `wi` and `N`); medium
  (pow for Facing, sqrt for Fresnel).
- **Proposed opcode**: `OP_LAYER_WEIGHT` — immediate: `weight_type` (enum),
  `normal_slot`. Pops 4 floats (blend, normal.xyz), pushes 1. Must run in a
  context that provides `wi` and `N`.

---

## 11. Mapping node (pkg219a companion)

- **Node name**: Mapping. **Cycles SVM opcode**: `NODE_MAPPING`
  (`src/kernel/svm/mapping.h`; `svm_mapping` in `src/kernel/svm/
  mapping_util.h`; `euler_to_transform` in `src/util/transform.h`). Enum
  `NodeMappingType` in `src/kernel/svm/types.h`. Manual:
  https://docs.blender.org/manual/en/latest/render/shader_nodes/vector/mapping.html
- **Inputs / outputs**: sockets `Vector` (vec3), `Location` (vec3),
  `Rotation` (vec3, Euler XYZ), `Scale` (vec3); output `Vector` (vec3).
  Mapping type (Point/Texture/Vector/Normal) is a **fixed enum parameter**.
- **Exact math** (`svm_mapping` in `src/kernel/svm/mapping_util.h`; `R` is
  the rotation matrix from `euler_to_transform(rotation)`):
  - **Point**: `R * (v * scale) + location`
  - **Texture**: `safe_divide(R^T * (v - location), scale)`
  - **Vector**: `R * (v * scale)`
  - **Normal**: `safe_normalize(R * safe_divide(v, scale))`
- **Per-texel cost class**: cheap-to-medium (matrix-vector multiply, 9
  mults + 6 adds; plus normalize for Normal).
- **Proposed opcode**: `OP_MAPPING` — immediate: `type` (enum). Pops 12
  floats (v.xyz, location.xyz, rotation.xyz, scale.xyz), pushes 3. The
  rotation matrix can be precomputed at compile time when rotation is
  constant (common case), reducing per-texel cost to a single mat3 multiply.

---

## Summary

### A. Proposed MINIMAL opcode set for pkg219b (VM core)

The smallest set that unblocks the owner's most common broken graphs — Color
Ramp, Mix, Math, Mapping downstream of a texture — plus the plumbing every
graph needs:

| Opcode | Pops | Pushes | Notes |
|---|---|---|---|
| `OP_CONST_F` | 0 | 1 | push float immediate |
| `OP_CONST_V3` | 0 | 3 | push vec3 immediate |
| `OP_MATH` | 3 | 1 | enum immediate; implement the common subset first: Add, Subtract, Multiply, Divide, Multiply Add, Power, Square Root, Absolute, Minimum, Maximum, Round, Floor, Ceil, Fraction, Truncated Modulo, Floored Modulo, Snap, Less Than, Greater Than, Sign, Compare |
| `OP_VEC_MATH` | 7 | 3 or 1 | enum immediate; common subset: Add, Subtract, Multiply, Divide, Dot Product, Length, Distance, Scale, Normalize, Cross Product, Multiply Add |
| `OP_MIX` | 7 | 3 | enum immediate + clamp flags; common subset: Mix, Add, Multiply, Subtract, Screen, Difference, Darken, Lighten, Overlay |
| `OP_MIX_F` / `OP_MIX_V` | 3 / 7 | 1 / 3 | modern Mix node float/vector data types (`endvalue_preserving_mix`) |
| `OP_RAMP` | 1 | 4 | baked table lookup (color.xyz + alpha); `OP_RAMP_COLOR`/`OP_RAMP_ALPHA` variants when only one output is live |
| `OP_MAPPING` | 12 | 3 | enum immediate; rotation matrix precomputed when constant |
| `OP_SEP_VEC` / `OP_COMBINE_VEC` | 3 / 1 | 1 / 3 | component index immediate |
| `OP_SEP_COLOR` / `OP_COMBINE_COLOR` | 3 / 3 | 3 / 3 | space enum (RGB first; HSV/HSL can defer) |
| `OP_RGB_TO_BW` | 3 | 1 | luma immediate |
| `OP_INVERT` | 4 | 3 | |
| `OP_GAMMA` | 4 | 3 | |
| `OP_BRIGHT_CONTRAST` | 5 | 3 | |
| `OP_HSV` | 7 | 3 | |
| `OP_MAP_RANGE` | 6 | 1 | enum immediate; Linear + Stepped first |
| `OP_CLAMP` | 3 | 1 | enum immediate |

This is ~18 opcodes. With `OP_MATH`/`OP_VEC_MATH`/`OP_MIX` carrying enum
immediates, pkg219b can ship the VM core + dispatch + stack + the constant
and plumbing ops, and pkg219c fills out the remaining enum values.

### B. Fuller opcode set deferred to pkg219c

- **Math**: all remaining enum values — Sine, Cosine, Tangent, Arcsine,
  Arccosine, Arctangent, Arctan2, Hyperbolic Sine/Cosine/Tangent, Exponent,
  Logarithm, Inverse Square Root, Wrap, Ping-pong, Smooth Minimum, Smooth
  Maximum, To Radians, To Degrees.
- **Vector Math**: remaining enum values — Project, Reflect, Refract,
  Faceforward, Snap, Wrap, Fraction, Absolute, Power, Sign, Minimum, Maximum,
  Sine, Cosine, Tangent, Round.
- **Mix**: remaining blend types — Divide, Dodge, Burn, Hue, Saturation,
  Value, Color, Soft Light, Linear Light, Exclusion.
- **Color Ramp**: if the VM evaluates the ramp directly instead of baking,
  the Ease/Cardinal/B-Spline interpolation formulas (section 4) become
  per-texel work; otherwise they are compile-time only.
- **Separate/Combine Color**: HSV and HSL spaces.
- **View-dependent**: `OP_FRESNEL`, `OP_LAYER_WEIGHT` (section 10) — these
  need shading context and are the only nodes in this document that cannot
  run in a texture-only pre-pass.
- **Texture Coordinate** (`NODE_TEX_COORD`, `src/kernel/svm/tex_coord.h`):
  handled by pkg219a (Coordinate + Mapping unification); note that the
  Normal, Reflection, Camera and Window coordinate types are also
  view-dependent (need `N`, `wi`, or the camera transform).

### C. View-dependent design constraint

Fresnel and Layer Weight read `sd->wi` (incoming direction) and the shading
normal `N` (defaulting to `sd->N`), and Fresnel additionally branches on the
backfacing flag (`src/kernel/svm/fresnel.h`). They therefore **cannot be
evaluated in a texture-only pre-pass** — their result depends on the view
ray, not just the texture coordinate. Design implication for the op-VM:

- The VM must be able to run in two contexts: (1) a texture pre-pass with a
  synthetic/placeholder `wi`/`N` for graphs that do not contain
  view-dependent nodes, and (2) the full shading pass where `wi` and `N` are
  available. A graph containing Fresnel/Layer Weight (or a view-dependent
  Texture Coordinate type) must be flagged at compile time and routed to the
  shading-time context.
- The same constraint applies to the Geometry node's Normal/Incoming outputs
  and to Light Path / Camera Data nodes if they are ever added to the VM.

### D. Sources

Cycles kernel (current main, `https://github.com/blender/cycles`):
- `src/kernel/svm/math_util.h` — `svm_math()`, `svm_vector_math()`,
  `svm_math_gamma_color()`
- `src/kernel/svm/math.h` — `svm_node_math()`, `svm_node_vector_math()`
- `src/kernel/svm/mix.h` — `svm_node_mix*()`
- `src/kernel/svm/color_util.h` — `svm_mix*()` blend helpers,
  `svm_brightness_contrast()`, `svm_separate_color()`/`svm_combine_color()`
- `src/kernel/svm/ramp.h`, `src/kernel/svm/ramp_util.h` — ramp table lookup
- `src/kernel/svm/sepcomb_color.h`, `src/kernel/svm/sepcomb_vector.h`
- `src/kernel/svm/convert.h` — `NODE_CONVERT_CF` (RGB to BW)
- `src/kernel/svm/invert.h`, `gamma.h`, `brightness.h`, `hsv.h`
- `src/kernel/svm/map_range.h`, `clamp.h`, `value.h`
- `src/kernel/svm/fresnel.h` — Fresnel + Layer Weight
- `src/kernel/svm/mapping.h`, `src/kernel/svm/mapping_util.h`
- `src/kernel/svm/tex_coord.h` — Texture Coordinate
- `src/kernel/svm/types.h` — `NodeMathType`, `NodeVectorMathType`, `NodeMix`,
  `NodeMapRangeType`, `NodeClampType`, `NodeCombSepColorType`,
  `NodeBlendWeightType`, `NodeMappingType`, `NodeTexCoord`
- `src/kernel/svm/node_types.h` — SVM node parameter structs
- `src/kernel/svm/node_types_template.h` — opcode list
- `src/util/math_base.h`, `src/util/math_float3.h` — safe-math helpers,
  `wrapf`, `pingpongf`, `smoothminf`, `project`, `reflect`, `refract`,
  `faceforward`, `safe_normalize`
- `src/util/color.h` — `rgb_to_hsv`, `hsv_to_rgb`, `rgb_to_hsl`, `hsl_to_rgb`
- `src/util/transform.h` — `euler_to_transform`
- `src/kernel/closure/bsdf_util.h` — `fresnel_dielectric_cos`
- `src/kernel/util/colorspace.h` — `linear_rgb_to_gray`
- `src/scene/shader_nodes.cpp` — `RGBRampNode::compile`

Blender-side (current main, `https://github.com/blender/blender`):
- `source/blender/blenkernel/intern/colorband.cc` — `BKE_colorband_evaluate`
  (ramp interpolation modes: Linear/Constant/Ease/Cardinal/B-Spline)
- `source/blender/blenkernel/intern/key.cc` — `key_curve_position_weights`
  (Cardinal/B-Spline weights)
- `intern/cycles/blender/util.h` — `colorramp_to_array` (table baking,
  `RAMP_TABLE_SIZE = 256`, 257 samples at `i/256`)
- `intern/cycles/blender/shader.cpp` — ColorRamp -> `RGBRampNode` conversion,
  `interpolate = (ipotype != COLBAND_INTERP_CONSTANT)`

Blender manual (all `https://docs.blender.org/manual/en/latest/`):
- `render/shader_nodes/converter/math.html`
- `render/shader_nodes/converter/vector_math.html`
- `render/shader_nodes/color/mix.html`
- `render/shader_nodes/converter/color_ramp.html`
- `render/shader_nodes/converter/separate_color.html`,
  `.../combine_color.html`, `.../separate_xyz.html`, `.../combine_xyz.html`,
  `.../rgb_to_bw.html`, `.../map_range.html`, `.../clamp.html`
- `render/shader_nodes/color/invert.html`, `.../gamma.html`,
  `.../bright_contrast.html`, `.../hue_saturation_value.html`
- `render/shader_nodes/input/value.html`, `.../rgb.html`, `.../fresnel.html`,
  `.../layer_weight.html`, `.../texture_coordinate.html`
- `render/shader_nodes/vector/mapping.html`

### E. Verification status

All formulas above were transcribed from the cited Cycles/Blender sources
fetched from the upstream repositories on 2026-08-23 (current `main`). No
operation in this document is marked UNVERIFIED. The one caveat: the exact
`RAMP_TABLE_SIZE` value (256) is confirmed by the Cycles/Eevee ramp
consistency PR (blender/blender#111082) and the `colorramp_to_array` code
path, but the macro definition itself was not located in a single header
during this pass — treat 256 as verified-by-behavior, not by macro location.