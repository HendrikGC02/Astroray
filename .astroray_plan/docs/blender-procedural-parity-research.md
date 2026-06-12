# Blender procedural-texture parity research (pkg115 Stage 1)

**Date:** 2026-06-10
**Package:** pkg115 — adopt Blender's shader node tree for textures/UVs
**Purpose:** per-evaluator audit of the engine's procedural textures against the
canonical Cycles SVM kernel implementations. Stage 2/3 implementation follows
this document. CLAUDE.md §6: every formula below is cited to the exact Cycles
file + function; no invented math.

All Cycles code was fetched 2026-06-10 from `main` at
`https://projects.blender.org/blender/blender/raw/branch/main/<path>`.

---

## 1. Sources and licenses

Astroray is MIT-licensed (`LICENSE`). Porting plan per file:

| Source file (Blender repo) | SPDX header (verified per file) | Use |
|---|---|---|
| `intern/cycles/kernel/svm/noise.h` | **BSD-3-Clause** — `SPDX-FileCopyrightText: 2009-2010 Sony Pictures Imageworks Inc., et al.` + `2011-2022 Blender Foundation`; "Adapted code from Open Shading Language" | Port (Perlin core) |
| `intern/cycles/kernel/svm/fractal_noise.h` | **Apache-2.0**, Blender Foundation 2011-2022 | Port (fBM stack) |
| `intern/cycles/kernel/svm/noisetex.h` | **Apache-2.0** | Port (Noise node eval) |
| `intern/cycles/kernel/svm/voronoi.h` | **Apache-2.0**; embedded notice: "SPDX-License-Identifier: MIT — Original code is copyright (c) 2013 Inigo Quilez" (Smooth Voronoi, Distance-to-Edge) | Port |
| `intern/cycles/kernel/svm/wave.h` | **Apache-2.0** | Port |
| `intern/cycles/kernel/svm/magic.h` | **Apache-2.0** | Port |
| `intern/cycles/kernel/svm/brick.h` | **Apache-2.0** | Port |
| `intern/cycles/kernel/svm/gradient.h` | **Apache-2.0** | Port |
| `intern/cycles/kernel/svm/checker.h` | **Apache-2.0** | Port |
| `intern/cycles/kernel/svm/white_noise.h` | **Apache-2.0** | Port |
| `intern/cycles/kernel/svm/mapping_util.h` | **Apache-2.0** | Port (Mapping node) |
| `intern/cycles/kernel/svm/tex_coord.h` | **Apache-2.0** | Reference (coord spaces) |
| `intern/cycles/util/hash.h` | **Apache-2.0** | Port (hash family — required by voronoi, white noise, noisetex offsets) |
| `intern/cycles/scene/shader_nodes.cpp` | **Apache-2.0** | Reference (socket defaults, implicit links, enums) |
| `source/blender/nodes/shader/nodes/node_shader_tex_*.cc` | **GPL-2.0-or-later**, 2005 Blender Authors | **Facts only** (socket defaults/enums). Do NOT copy code — GPL. All math comes from the Apache/BSD Cycles kernel files above. |
| Blender manual (`blender/blender-manual` repo, `manual/render/shader_nodes/...`) | CC-BY-SA 4.0 (Blender manual license) | Reference (semantics quotes) |
| Blender 4.1 release notes (`blender/blender-developer-docs`, `docs/release_notes/4.1/nodes_physics.md`, `rendering.md`) | — | Reference (Musgrave removal) |

License compatibility: Apache-2.0 and BSD-3-Clause code may be incorporated
into the MIT-licensed engine provided the original SPDX/copyright notices are
retained in the ported files (Stage 2: keep the SPDX header block + "ported
from Cycles `svm/<file>.h::<function>`" comment at the top of each evaluator).
The Inigo Quilez MIT attribution must be carried along with the smooth-Voronoi
and distance-to-edge ports.

**Musgrave note (critical):** `musgrave.h` **no longer exists** in Cycles
`main`. In **Blender 4.1 the Musgrave Texture node was removed** and folded
into the Noise Texture node. Release notes (4.1 `rendering.md`): "The Musgrave
Texture node was replaced by the Noise Texture node. Existing shader node
setups are converted automatically, and the resulting renders are identical.
The Dimension input is replaced by a Roughness input [Roughness =
Lacunarity^(−Dimension)], and the Detail input requires adjustment: subtract 1
from the old value." The old Musgrave modes live on as the Noise node's
`noise_type` (fBM / Multifractal / Hybrid Multifractal / Ridged Multifractal /
Hetero Terrain), implemented in `fractal_noise.h`.

---

## 2. Engine inventory

### 2.1 Texture classes (`include/advanced_features.h`)

12 texture classes + base. The plugin registry (`plugins/textures/*.cpp`,
e.g. `noise.cpp:4` `class NoisePlugin : public NoiseTexture`) are thin
ParamDict wrappers over these same classes — auditing the header covers both.

| # | Class | Lines | Parameters (ctor) | Math it actually evaluates |
|---|---|---|---|---|
| 1 | `SolidColor` | 165-170 | color | constant |
| 2 | `CheckerTexture` | 172-182 | c1, c2, scale=10 | `sin(s·x)·sin(s·y)·sin(s·z) < 0 ? odd : even` (RTOW-style sine product) |
| 3 | `NoiseTexture` | 184-193 | scale=1 | `noise(p) = fract(sin(p·(12.9898, 78.233, 37.719))·43758.5453)` — the GLSL sin-hash one-liner. **Unsigned white noise in [0,1), NOT Perlin.** |
| 4 | `ImageTexture` | 195-230 | data,w,h | nearest-neighbor, u clamped, v flipped; no interpolation, no repeat |
| 5 | `MarbleTexture` | 232-246 | scale=1 | `0.5(1+sin(s·z + 10·turb(p)))`, turb = 7-octave sum of sin-hash noise, weight 0.5, lac 2 |
| 6 | `WoodTexture` | 248-258 | scale=1 | rings from `r=√(x²+z²)`, sin-hash noise, pow shaping |
| 7 | `GradientTexture` | 265-287 | type, c1, c2, scale=1 | 7 types; see §5.3 |
| 8 | `WaveTexture` | 291-336 | bandDir, profile, scale=5, distortion=0, detail=2, roughness=0.5, lacunarity=2, c1, c2 | `phase=(x+d)·π` (bands) or `(r+d)·π` (rings); d = distortion·turb(sin-hash, int steps); 3 profiles; see §5.4 |
| 9 | `MagicTexture` | 339-366 | depth=2, scale=5, distortion=1, c1, c2 | ad-hoc sin/cos cascade with `scale·π` args, `distortion·0.25`, depth ≤5, scalar 2-color lerp; see §5.5 |
| 10 | `VoronoiTexture` | 371-429 | scale=5, randomness=1, distMetric, feature, smoothness=1, c1, c2 | 3×3×3 cell search, sin-hash jitter (`hash3`, lines 385-390), metrics Euclidean/Manhattan/Chebychev/Minkowski(p fixed 2.5), features F1/F2/(F1+F2)/2 / F2−F1 / smoothF1 (`−log(Σh³)/3`), output = clamp + 2-color lerp; see §5.6 |
| 11 | `BrickTexture` | 432-456 | brick, mortar colors, bw=0.5, bh=0.25, mortarSize=0.02, offset=0.5, scale=5 | **UV-driven** (ignores 3D p); alternate-row offset; mortar = half-band test; see §5.7 |
| 12 | `MusgraveTexture` | 459-501 | type, scale=5, detail=2, dimension=2, lacunarity=2, gain=1, c1, c2 | fBm/ridged on **sin-hash white noise**, `H = max(0.001, dimension−1)`, `amp *= lacunarity^(−H)`, int-truncated detail; types 1 (multifractal) and 3 (hybrid) silently fall into the fBm branch; see §5.8 |

### 2.2 Coordinate model (`advanced_features.h:9-163`)

`Texture::CoordMode` = {UV, Generated, Object, Camera, Normal, Reflection,
Window} (lines 11-19). Resolution in `textureCoordinates()` (lines 71-116):

| Mode | Engine returns (uv, p) |
|---|---|
| UV | `(rec.uv or named layer, rec.point)` — **3D point = world hit position** |
| Generated | bbox-normalized `rec.objectPoint`, clamped [0,1] |
| Object | `rec.objectPoint` |
| Camera | `rel·U, rel·V, rel·(−W)` against the stored camera frame |
| Normal | `rec.normal·0.5+0.5` — **remapped to [0,1], world(shading)-space** |
| Reflection | reflect incoming dir, p = direction; uv = equirect via `directionToUV` |
| Window | `rec.windowUV` |

Per-texture UV transform (`applyUVTransform`, lines 33-47): Blender "Point"
Mapping order scale→rotate(Z only)→translate, **applied to the 2D uv only —
never to the 3D point `p`**. Since 9 of the 12 evaluators sample `p`, a
Blender Mapping node currently has **no effect** on engine 3D procedurals.

### 2.3 Standalone factory API (kept, per spec)

`module/blender_module.cpp`: `TextureManager::createProceduralTexture`
(lines 192-268, string types: checker / noise / marble / wood / gradient /
wave / magic / voronoi / brick / musgrave, positional float params),
`setTextureCoordMode` (269-272), `setTextureUVTransform` (275-279),
`setTextureUVLayerName` (280-282). pybind bindings at lines 2089-2101
(`create_procedural_texture`, `set_texture_coord_mode`,
`set_texture_uv_transform`, `set_texture_uv_layer`). Registry plugins:
`plugins/textures/{checker,noise,gradient,voronoi,brick,musgrave,magic,wave,image}.cpp`.

---

## 3. Cycles reference, node by node

Defaults below are from the GPL node-definition `.cc` files (facts only) and
the Apache-2.0 `scene/shader_nodes.cpp` socket declarations; math is from the
Apache/BSD kernel files.

### 3.0 Shared foundation

- **Perlin core** — `svm/noise.h` (BSD-3-Clause):
  `fade(t) = t³(t(6t−15)+10)`; `grad3(hash,x,y,z)` picks from 12 gradient
  directions via `hash & 15` (`noise.h:142-148`); `perlin_3d(x,y,z)`
  (`noise.h:181-210`) = trilinear `tri_mix` of `grad3(hash_uint3(X..Z+1), …)`
  over the cell corners with faded weights. Signed range scaled by
  `noise_scale3(r) = 0.9820f * r` (`noise.h:679-682`);
  `snoise_3d(p) = noise_scale3(perlin_3d(p))` (≈[−1,1], `noise.h:725-736`);
  `noise_3d(p) = 0.5·snoise_3d(p)+0.5` (`noise.h:738-741`). 1D/2D/4D variants
  exist (`perlin_1d/2d/4d`, `snoise_1d/2d/4d`).
- **Hash family** — `util/hash.h` (Apache-2.0): `hash_uint3` (Jenkins,
  line 153), `hash_float_to_float` (217), `hash_int3_to_float3` (248),
  `hash_float3_to_float3` (283), etc. Required by Perlin, Voronoi, White
  Noise, and the noisetex random offsets.
- **fBM stack** — `svm/fractal_noise.h` (Apache-2.0), all functions overloaded
  for float/float2/float3/float4 (1D-4D):
  - `noise_fbm(p, detail, roughness, lacunarity, normalize)`
    (`fractal_noise.h:63-86` for 3D):
    ```
    fscale=1; amp=1; maxamp=0; sum=0;
    for (i = 0; i <= (int)detail; i++) {
        sum += snoise_3d(fscale*p) * amp;  maxamp += amp;
        amp *= roughness;  fscale *= lacunarity;
    }
    rmd = detail - floor(detail);
    if (rmd != 0) { sum2 = sum + snoise_3d(fscale*p)*amp;
        return normalize ? mix(0.5*sum/maxamp+0.5, 0.5*sum2/(maxamp+amp)+0.5, rmd)
                         : mix(sum, sum2, rmd); }
    return normalize ? 0.5*sum/maxamp+0.5 : sum;
    ```
    **Fractional detail = lerp between octave counts; normalize divides by
    Σamp and remaps to [0,1].**
  - `noise_multi_fractal` (`:159-179`): `value *= (pwr·snoise(p) + 1)` per
    octave, `pwr *= roughness`; fractional remainder
    `value *= (rmd·pwr·snoise(p) + 1)`.
  - `noise_hetero_terrain(p, detail, roughness, lacunarity, offset)`
    (`:258-284`): `value = offset + snoise(p)`; per octave
    `increment = (snoise(p)+offset)·pwr·value; value += increment;
    pwr *= roughness`; fractional `value += rmd·increment`.
  - `noise_hybrid_multi_fractal(p, detail, roughness, lacunarity, offset, gain)`
    (`:378-407`): weight-gated additive loop —
    `weight=min(weight,1); signal=(snoise(p)+offset)·pwr; pwr*=roughness;
    value += weight·signal; weight *= gain·signal;` stops when
    `weight ≤ 0.001`.
  - `noise_ridged_multi_fractal(p, detail, roughness, lacunarity, offset, gain)`
    (`:496-521`): `signal = (offset − |snoise(p)|)²` first octave; then
    `weight = saturate(signal·gain); signal = (offset−|snoise(p)|)²·weight;
    value += signal·pwr; pwr *= roughness`.

### 3.1 Noise Texture (`ShaderNodeTexNoise`) — includes Musgrave since 4.1

- Node eval: `svm/noisetex.h` (Apache-2.0). `svm_node_tex_noise`
  (`noisetex.h:245+`): clamps `detail = clamp(detail, 0, 15)`,
  `roughness = max(roughness, 0)`, then **`vector *= scale; w *= scale`**.
  Dimensions 1-4 (`w` is the 4th).
- `noise_texture_3d` (`noisetex.h:161-201`): distortion is a **per-component
  3D domain warp**:
  ```
  if (distortion != 0)
      p += ( snoise_3d(p + random_float3_offset(0))·distortion,
             snoise_3d(p + random_float3_offset(1))·distortion,
             snoise_3d(p + random_float3_offset(2))·distortion );
  value = noise_select(p, detail, roughness, lacunarity, offset, gain, type, normalize);
  color = (value, noise_select(p + random_float3_offset(3), …),
                  noise_select(p + random_float3_offset(4), …));
  ```
  `random_float3_offset(seed)` = components `100 + hash_float2_to_float(seed,k)·100`
  (range [100,200], `noisetex.h:32-37`).
- `noise_select` (`noisetex.h:48-78`) dispatches `noise_type`:
  MULTIFRACTAL → `noise_multi_fractal`; FBM → `noise_fbm` (only type that uses
  `normalize`); HYBRID_MULTIFRACTAL / RIDGED_MULTIFRACTAL → with
  `offset, gain`; HETERO_TERRAIN → with `offset`.
- Node defaults (`node_shader_tex_noise.cc`, GPL — facts only): Scale 5.0,
  Detail 2.0 [0,15], Roughness 0.5 [0,1], Lacunarity 2.0, Offset 0.0,
  Gain 1.0, Distortion 0.0; `noise_type` default **fBM**; `normalize`
  default **true**. Outputs: Fac (float), Color.

### 3.2 Voronoi Texture (`ShaderNodeTexVoronoi`)

- Kernel: `svm/voronoi.h` (Apache-2.0 + MIT IQ attribution).
- `VoronoiParams` (`voronoi.h:30-42`): scale, detail, roughness, lacunarity,
  smoothness, exponent, randomness, max_distance, normalize, feature, metric.
- Distance metrics (`voronoi_distance`, `voronoi.h:57-72`):
  Euclidean `distance(a,b)`; Manhattan `reduce_add(fabs(a−b))`;
  Chebychev `reduce_max(fabs(a−b))`;
  Minkowski `pow(reduce_add(fabs(a−b)^exponent), 1/exponent)`.
  Host enum (`scene/shader_nodes.cpp:1319-1324`): euclidean / manhattan /
  chebychev / minkowski, default euclidean.
- `voronoi_f1` 3D (`voronoi.h:479-510`): 3×3×3 neighborhood;
  `pointPosition = cellOffset + hash_int3_to_float3(cellPosition+cellOffset) · randomness`;
  outputs distance, `color = hash_int3_to_float3(cell)`, position.
- `voronoi_smooth_f1` 3D (`voronoi.h:512-552`): **5×5×5** neighborhood
  (−2..2); polynomial smooth-min:
  ```
  h = (h==-1) ? 1 : smoothstep(0,1, 0.5 + 0.5·(smoothDistance−d)/smoothness);
  correction = smoothness·h·(1−h);
  smoothDistance = mix(smoothDistance, d, h) − correction;
  correction /= 1 + 3·smoothness;
  smoothColor   = mix(smoothColor, cellColor, h) − correction;
  smoothPosition= mix(smoothPosition, pointPosition, h) − correction;
  ```
- `voronoi_f2` 3D (`voronoi.h:553-596`): tracks two nearest, returns F2
  distance/color/position.
- `voronoi_distance_to_edge` 3D (`voronoi.h:597+`): IQ two-pass perpendicular
  edge distance. `voronoi_n_sphere_radius` 3D (`voronoi.h:645+`): half the
  distance between the closest point and its closest neighbor.
- **Fractal layering** `fractal_voronoi_x_fx` (`voronoi.h:940-992`): octave
  loop `i <= ceil(detail)` with `scale *= lacunarity`, `amplitude *=
  roughness`, fractional-remainder lerp identical in spirit to `noise_fbm`;
  `if (normalize) { distance /= max_amplitude·max_distance; color /= max_amplitude; }`;
  finally `position = safe_divide(position, params.scale)`.
- Node-side conditioning (`svm_node_tex_voronoi`, `voronoi.h:1065+`):
  `detail = clamp(detail,0,15)`, `roughness = clamp(roughness,0,1)`,
  `randomness = clamp(randomness,0,1)`,
  **`smoothness = clamp(smoothness/2, 0, 0.5)`**; `coord *= scale`;
  `max_distance = voronoi_distance(0, (0.5+0.5·randomness)·ones) ·
  (feature==F2 ? 2 : 1)`; distance-to-edge uses
  `max_distance = 0.5 + 0.5·randomness`.
- Node defaults (`node_shader_tex_voronoi.cc` GPL facts +
  `scene/shader_nodes.cpp:1336-1350`): Scale 5.0, Detail 0.0, Roughness 0.5,
  Lacunarity 2.0, Smoothness 1.0 (UI; Cycles socket 5.0 — UI value is what is
  passed), Exponent 0.5, Randomness 1.0; feature default F1; normalize
  default **false**; dims 1-4. Outputs: Distance, Color, Position, W, Radius.

### 3.3 Wave Texture (`ShaderNodeTexWave`)

- Kernel: `svm/wave.h` (Apache-2.0), `svm_wave` — full quote in repo of
  record; key lines:
  - `p = (p + 0.000001)·0.999999` (precision guard); input is already
    `co * scale` (`svm_node_tex_wave`).
  - Bands: X `n = p.x·20`; Y `n = p.y·20`; Z `n = p.z·20`;
    Diagonal `n = (p.x+p.y+p.z)·10`.
  - Rings: zero one axis (X→`(0,1,1)`, Y→`(1,0,1)`, Z→`(1,1,0)`, Spherical→
    none), then `n = len(rp)·20`.
  - `n += phase;`
  - `if (distortion != 0) n += distortion · (noise_fbm(p·dscale, detail,
    droughness, 2.0, true)·2 − 1);` — real fBM (lacunarity fixed 2.0,
    normalized then remapped to [−1,1]).
  - Profiles: SIN `0.5 + 0.5·sin(n − π/2)`; SAW `n /= 2π; return n − floor(n)`;
    TRI `n /= 2π; return |n − floor(n + 0.5)|·2`.
- Node defaults (`node_shader_tex_wave.cc`, GPL facts): Scale 5.0,
  Distortion 0.0, Detail 2.0 [0,15], Detail Scale 1.0, Detail Roughness 0.5,
  Phase Offset 0.0; wave_type Bands (default), bands_direction X,
  rings_direction X, profile Sine. Outputs: Color (grayscale f), Fac.

### 3.4 Magic Texture (`ShaderNodeTexMagic`)

- Kernel: `svm/magic.h::svm_magic` (Apache-2.0), verbatim core:
  ```
  px = fmod(p.x·scale, 2π); py = …; pz = …;          // NaN/precision guard
  x = sin((px+py+pz)·5); y = cos((−px+py−pz)·5); z = −cos((−px−py+pz)·5);
  if (n>0) { x*=dist; y*=dist; z*=dist; y = −cos(x−y+z); y*=dist;
   if (n>1) { x =  cos(x−y−z); x*=dist;
    if (n>2) { z =  sin(−x−y−z); z*=dist;
     if (n>3) { x = −cos(−x+y−z); x*=dist;
      if (n>4) { y = −sin(−x+y+z); y*=dist;
       if (n>5) { y = −cos(−x+y+z); y*=dist;
        if (n>6) { x =  cos(x+y+z); x*=dist;
         if (n>7) { z =  sin(x+y−z); z*=dist;
          if (n>8) { x = −cos(−x−y+z); x*=dist;
           if (n>9) { y = −sin(x−y+z); y*=dist; }}}}}}}}}
  if (dist != 0) { dist *= 2; x/=dist; y/=dist; z/=dist; }
  return (0.5−x, 0.5−y, 0.5−z);
  ```
- Node: Scale 5.0, Distortion 1.0, depth property default 2 (0-10 branches);
  Fac output = `average(color)` (`svm_node_tex_magic`). Output is genuine RGB.

### 3.5 Brick Texture (`ShaderNodeTexBrick`)

- Kernel: `svm/brick.h` (Apache-2.0). `brick_noise(uint)` integer hash
  (`brick.h:14-21`, constants 1013, 60493, 19990303, 1376312589).
  `svm_brick(p·scale, …)` (`brick.h:23-70`):
  ```
  rownum = floor(p.y / row_height);
  if (offset_frequency && squash_frequency) {
      brick_width *= (rownum % squash_frequency) ? 1 : squash_amount;
      offset = (rownum % offset_frequency) ? 0 : brick_width·offset_amount;
  }
  bricknum = floor((p.x+offset)/brick_width);
  x = (p.x+offset) − brick_width·bricknum;  y = p.y − row_height·rownum;
  tint = saturate(brick_noise((rownum<<16) + (bricknum & 0xFFFF)) + bias);
  min_dist = min(min(x,y), min(brick_width−x, row_height−y));
  mortar = (min_dist ≥ mortar_size) ? 0
         : (mortar_smooth == 0) ? 1
         : smoothstep((1 − min_dist/mortar_size) / mortar_smooth);   // note inversion
  ```
  Node combine (`svm_node_tex_brick`): if not full mortar,
  `color1 = mix(color1, color2, tint)` (per-brick random tint!), then
  `color = mix(color1, mortar_color, f)`; Fac = f.
- Node defaults (`node_shader_tex_brick.cc`, GPL facts): Color1
  (0.8,0.8,0.8), Color2 (0.2,0.2,0.2), Mortar (0,0,0), Scale 5.0, Mortar
  Size 0.02 [0,0.125], Mortar Smooth 0.1, Bias 0, Brick Width 0.5, Row
  Height 0.25; properties offset 0.5, offset_frequency 2, squash 1.0,
  squash_frequency 2.

### 3.6 Gradient Texture (`ShaderNodeTexGradient`)

- Kernel: `svm/gradient.h::svm_gradient` (Apache-2.0), verbatim:
  Linear `x`; Quadratic `r = max(x,0); r·r`;
  Easing `r = clamp(x,0,1); t = r²; 3t − 2t·r`;
  Diagonal `(x+y)·0.5`; Radial `atan2(y,x)/2π + 0.5`;
  Quadratic Sphere / Spherical: `r = max(0.999999 − √(x²+y²+z²), 0)`, return
  `r²` / `r`. Node applies `f = saturate(f)`; Color = (f,f,f), Fac = f.
- Node (`node_shader_tex_gradient.cc`, GPL facts): no Scale/color sockets,
  only Vector + gradient_type (default `SHD_BLEND_LINEAR`).

### 3.7 Checker Texture (`ShaderNodeTexChecker`)

- Kernel: `svm/checker.h::svm_checker` (Apache-2.0), verbatim:
  ```
  p = (p + 0.000001)·0.999999;             // per component, precision guard
  xi = abs((int)floor(p.x)); yi = …; zi = …;
  return ((xi % 2 == yi % 2) == (zi % 2)) ? 1 : 0;
  ```
  applied to `co * scale`; Color = f ? color1 : color2; Fac = f.
- Node defaults (`node_shader_tex_checker.cc:24-44`, GPL facts): Color1
  (0.8,0.8,0.8), Color2 (0.2,0.2,0.2), Scale 5.0.

### 3.8 White Noise Texture (`ShaderNodeTexWhiteNoise`)

- Kernel: `svm/white_noise.h::svm_node_tex_white_noise` (Apache-2.0):
  value = `hash_float_to_float(w)` / `hash_float2_to_float` /
  `hash_float3_to_float(vector)` / `hash_float4_to_float((vector,w))` by
  dimensions (default 3); color = the matching `hash_*_to_float3`. No other
  parameters.

### 3.9 Coordinates: `ShaderNodeTexCoord`, `ShaderNodeMapping`, `ShaderNodeUVMap`

- Kernel: `svm/tex_coord.h` (Apache-2.0) + host `scene/shader_nodes.cpp`
  (Apache-2.0) + manual `manual/render/shader_nodes/input/texture_coordinate.rst`.
  - **Generated**: surface → attribute `ATTR_STD_GENERATED`
    (`TextureCoordinateNode::attributes`, `shader_nodes.cpp:4037-4046`);
    manual: "from 0.0 to 1.0 over the bounding box of the non-deformed mesh".
    Background → position; volume → `volume_normalized_position`.
  - **Object**: `object_inverse_position_transform` of P (object space;
    optional other-object transform `NODE_TEXCO_OBJECT_WITH_TRANSFORM`)
    (`tex_coord.h:101-112`).
  - **Normal**: `sd->N` through `object_inverse_normal_transform` — **signed
    object-space normal, no remap** (`tex_coord.h:113-121`).
  - **Camera**: `transform_point(kernel_data.cam.worldtocamera, P)`
    (`tex_coord.h::svm_texco_camera`, lines 78-89).
  - **Window**: `camera_world_to_ndc(…, sd->P)` with `z = 0` — 0..1 screen
    NDC (`tex_coord.h:128-147`).
  - **Reflection**: `−reflect(I, N)` — the raw reflection **direction**, not
    a UV (`tex_coord.h::svm_texco_reflection`, lines 68-75).
  - **UV**: attribute `ATTR_STD_UV`; `ShaderNodeUVMap` selects a named layer.
- **Implicit default**: every procedural texture node's unconnected Vector
  socket resolves to **Generated** coordinates —
  `SOCKET_IN_POINT(vector, "Vector", zero_float3(),
  SocketType::LINK_TEXTURE_GENERATED)` for noise/voronoi/wave/magic/brick/
  gradient/checker/white-noise (`scene/shader_nodes.cpp:926-1724`), while
  `ShaderNodeTexImage` uses `LINK_TEXTURE_UV` (`shader_nodes.cpp:284`).
  Manual (`textures/noise.rst:22-24`): "defaults to *Generated* texture
  coordinates if the socket is left unconnected."
- **Mapping node**: `svm/mapping_util.h::svm_mapping` (Apache-2.0), verbatim:
  ```
  rotationTransform = euler_to_transform(rotation);            // XYZ euler
  POINT:   transform_direction(rot, vector*scale) + location
  TEXTURE: safe_divide(transform_direction_transposed(rot, vector−location), scale)  // inverse of POINT
  VECTOR:  transform_direction(rot, vector*scale)              // no translation
  NORMAL:  safe_normalize(transform_direction(rot, safe_divide(vector, scale)))
  ```
  Manual (`utilities/vector/mapping.rst`): Point order Scale→Rotate→Translate;
  Texture is the inverse (Translate→Rotate→Scale, inverted); Vector = Point
  with zero translation; Normal = inverse-transpose + normalize.

---

## 4. Coordinate-space divergence summary

| Blender output | Engine CoordMode | Verdict |
|---|---|---|
| Generated (0..1 undeformed bbox) | `Generated` (bbox-normalized objectPoint, clamped) | **Match** (engine uses current object-space point — fine for rigid meshes; clamp is engine-only, harmless on-surface) |
| Object | `Object` | **Match** (`rec.objectPoint`) |
| UV / UVMap node | `UV` + `setUVLayerName` | **Match** for the 2D part. Divergence: engine hands `p = rec.point` (world!) to 3D evaluators in UV mode — Blender would use the UV vector `(u,v,0)`. Must pass `(u,v,0)` as the 3D coord when a texture is UV-driven. |
| Camera | `Camera` | Same construction (world→camera frame). Sign convention of the forward axis must be verified visually against Cycles `worldtocamera` in Stage 3 (engine uses `rel·(−W)` for z). |
| Window (0..1 NDC, z=0) | `Window` | **Match** |
| Normal (signed object-space N) | `Normal` (world-space, remapped `0.5n+0.5`) | **Divergence** — engine must output the signed object-space normal, no remap (`tex_coord.h:113-121`). |
| Reflection (raw direction) | `Reflection` (direction as p; equirect uv) | **Match for 3D textures** (p = direction). The equirect-UV projection is an engine extra; keep for standalone. |
| Mapping node (4 types, full XYZ euler, 3D) | `setUVTransform` (Point-type only, Z-rot only, **2D uv only**) | **Major divergence** — transform never reaches the 3D coordinate used by 9/12 evaluators. Stage 2 must apply a full 3D affine (per `svm_mapping`) to the resolved coordinate (both uv and p), supporting at least POINT; TEXTURE/VECTOR/NORMAL types per node setting. |
| Implicit default (unconnected Vector → Generated) | factory default `coord_mode="UV"` | **Divergence in wiring** — addon translator must pass `GENERATED` whenever a texture node's Vector input is unconnected (UV only for Image Texture). |

---

## 5. Divergence table per engine evaluator

Legend: severity ▲ = full rewrite/port, ◆ = formula fixes, ● = parameter/wiring only.

### 5.1 `CheckerTexture` ↔ `ShaderNodeTexChecker` ▲(small)

| Aspect | Engine (`advanced_features.h:172-182`) | Blender (`svm/checker.h`) | Action |
|---|---|---|---|
| Cell function | `sin(s·x)sin(s·y)sin(s·z) < 0` | floor-parity `((xi%2==yi%2)==(zi%2))` on `co·scale` with `(p+1e-6)·0.999999` guard | Replace evaluator with svm_checker port |
| Cell size | period `2π/s` per axis | `1/scale` | comes free with port |
| Params | c1, c2, scale (default 10) | Color1, Color2, Scale (default 5) | map 1:1; factory default unchanged for back-compat |
| Coords | 3D p ✓ | `co·scale` | ✓ |

### 5.2 `NoiseTexture` ↔ (closest: `ShaderNodeTexWhiteNoise`) — and the real Noise node needs a NEW evaluator ▲

- Engine `NoiseTexture` (`advanced_features.h:184-193`) is the GLSL sin-hash
  **white noise**, not Perlin. It cannot drive `ShaderNodeTexNoise`.
- New evaluator required for Noise node parity: port `perlin_3d` + `snoise_*`
  (`svm/noise.h`, BSD-3) + the five `fractal_noise.h` families + the
  `noisetex.h` wrapper (distortion warp, random offsets, color channels,
  detail clamp [0,15], `vector *= scale`, normalize). Dimensions: 3D first
  (engine textures are `value(uv, p)`); 1D/2D/4D optional later (note 4D `w`
  socket has no engine plumbing — document as non-goal or add a `w` param).
- Engine `NoiseTexture` maps loosely to White Noise; for actual White Noise
  parity port `hash_float3_to_float/float3` (`util/hash.h`) — the sin-hash has
  precision artifacts at large coords and a different pattern.
- Musgrave translation (pre-4.1 files / 4.1+ Noise node): engine factory
  "musgrave" should be re-mapped onto the new noise evaluator with
  `noise_type`, using the documented conversion `roughness =
  lacunarity^(−dimension)`, `detail = detail_old − 1` (4.1 release notes).

### 5.3 `GradientTexture` ↔ `ShaderNodeTexGradient` ◆

| Type | Engine (`advanced_features.h:273-286`) | Blender (`svm/gradient.h`) | Diverges? |
|---|---|---|---|
| linear | `clamp(x,0,1)` | `x` then saturate | match |
| quadratic | `clamp(x·x,0,1)` | `max(x,0)²` then saturate | **yes for x<0**: engine gives x², Blender 0 |
| easing | `r=clamp(x,0,1); r²(3−2r)` | same | match |
| diagonal | `(x+y)·0.5` clamped | same + saturate | match |
| spherical | `t = clamp(len(p),0,1)` (increases outward) | `max(0.999999 − len, 0)` (**decreases** outward) | **yes — inverted** |
| quadratic sphere | `1 − clamp(len²,0,1)` | `(max(0.999999 − len, 0))²` | **yes** — `1−r²` vs `(1−r)²` |
| radial | `fmod(atan2(y,x)/2π + 1, 1)` | `atan2(y,x)/2π + 0.5` | **yes — half-turn phase offset** |
| extras | engine has scale + 2 colors | node has neither (Fac/grayscale only) | keep for standalone; addon passes scale=1, colors (0,0,0)/(1,1,1) |
| enum order | engine ints 0-6: lin,quad,ease,diag,**sph,quadSph,radial** | Blender identifiers LINEAR…; kernel order lin,quad,ease,diag,**radial**,quadSph,sph | addon maps bpy identifier→engine int explicitly; fix engine formulas in place |

### 5.4 `WaveTexture` ↔ `ShaderNodeTexWave` ▲

| Aspect | Engine (`advanced_features.h:291-336`) | Blender (`svm/wave.h::svm_wave`) |
|---|---|---|
| Phase scale | bands `(x+d)·π` | `p.x·20` (X), `p.y·20`, `p.z·20`, diagonal `(x+y+z)·10` — on `co·scale`; **factor 20/π ≈ 6.37 denser** |
| Rings | full radius `√(x²+y²+z²)·π` | axis-zeroing options then `len(rp)·20`; spherical = no zeroing |
| Phase offset | none | `n += phase` (socket, default 0) |
| Distortion | `distortion·turb()`, turb = int-step loop of **unsigned sin-hash** noise, params detail/roughness/lacunarity free | `distortion·(noise_fbm(p·dscale, detail, droughness, 2.0, true)·2−1)` — signed, real Perlin fBM, **lacunarity fixed 2.0**, fractional detail |
| Profiles | sine `0.5+0.5 sin(phase)`; saw `1−fmod(phase/π,1)` (descending, period π); triangle period π | sine `0.5+0.5·sin(n−π/2)`; saw `frac(n/2π)` (ascending, period 2π); tri `|frac-based|·2` period 2π |
| Detail scale | none | `dscale` socket (Detail Scale 1.0) |
| Action | rewrite evaluator as svm_wave port (needs noise_fbm from 5.2); extend factory params (band/ring direction, phase, dscale) | |

### 5.5 `MagicTexture` ↔ `ShaderNodeTexMagic` ▲

Engine (`advanced_features.h:339-366`) vs `svm/magic.h::svm_magic` (§3.4):
wrong trig arguments (`scale·π` vs `fmod(p·scale, 2π)` then `·5`), wrong
distortion application (`0.25·distortion` pre-multiplies vs per-branch
`*= distortion` and final `/(2·distortion)`), depth capped at 5 vs 10, and the
output collapses RGB to a scalar 2-color lerp while Blender outputs true RGB
`(0.5−x, 0.5−y, 0.5−z)` with Fac = average. Action: verbatim port of
`svm_magic`; keep factory colors as an optional standalone tint (apply via
Fac) so existing scripts keep working.

### 5.6 `VoronoiTexture` ↔ `ShaderNodeTexVoronoi` ▲(largest)

| Aspect | Engine (`advanced_features.h:371-429`) | Blender (`svm/voronoi.h`) |
|---|---|---|
| Cell jitter hash | sin-hash `hash3` | `hash_int3_to_float3` (`util/hash.h:248`) — **different pattern layout; identical-hash port required for stills to match** |
| Metrics | Euclid/Manhattan/Chebychev/Minkowski **p=2.5 fixed** | same four, Minkowski exponent socket (default 0.5) |
| Features | F1, F2, (F1+F2)/2, F2−F1, smoothF1 (`−log Σh³ /3`) | F1, F2, Smooth F1 (smoothstep+correction, 5×5×5), Distance-to-Edge, N-Sphere Radius |
| Smoothness | raw, engine formula is a different smooth-min | node clamps `smoothness/2 → [0,0.5]`; math per §3.2 |
| Fractal octaves | none | `fractal_voronoi_x_fx` detail [0,15] / roughness / lacunarity + normalize |
| Outputs | clamp(val,0,1) lerp of two colors | Distance (optionally normalized by `max_amplitude·max_distance`), Color (cell hash color), Position |
| Action | port voronoi_f1/f2/smooth_f1, voronoi_distance(+exponent param), fractal wrapper, hash family; expose feature enum matching Blender; keep engine features 2/3 (F1+F2, F2−F1) standalone-only; addon maps Distance→Fac-style gray or Color output per link | |

### 5.7 `BrickTexture` ↔ `ShaderNodeTexBrick` ▲

| Aspect | Engine (`advanced_features.h:432-456`) | Blender (`svm/brick.h`) |
|---|---|---|
| Coordinate | **2D uv · scale** | 3D `co·scale` using p.x/p.y |
| Row offset | every other row, `offset·brickWidth` | `offset_frequency` (default 2), plus **squash** `squash_amount/squash_frequency` |
| Mortar | interior test with `mortarSize/2` per side → total gap `mortarSize` | `min_dist < mortar_size` per side → total gap `2·mortar_size`; plus `mortar_smooth` smoothstep |
| Brick color variation | none | per-brick `tint = saturate(brick_noise((row<<16)+(brick&0xFFFF)) + bias)` mixing Color1→Color2 |
| Defaults | brick (0.7,0.35,0.2), mortar 0.9 gray | Color1 0.8, Color2 0.2, Mortar black; addon passes node values so only standalone defaults differ |
| Action | port `svm_brick` + `brick_noise`; switch to 3D vector input; extend factory params (bias, mortar_smooth, offset/squash frequencies, color2) | |

### 5.8 `MusgraveTexture` ↔ Noise node `noise_type` (Musgrave removed in 4.1) ▲

Engine (`advanced_features.h:459-501`): sin-hash white noise (not Perlin);
`steps = max(1,(int)detail)` (no fractional blend); `H = max(0.001,
dimension−1)`; `amp *= lacunarity^(−H)`; types multifractal/hybrid fall
through to fBm; ridged variant is ad-hoc (`|noise−0.5|·2` ridges). Blender:
the five exact `fractal_noise.h` functions (§3.0) on signed Perlin with
roughness as the per-octave amplitude factor, offset/gain inputs, fractional
detail, normalize. Action: retire the engine math in favor of the §5.2 noise
evaluator with `noise_type`; factory `"musgrave"` becomes a compatibility
alias applying `roughness = lacunarity^(−dimension)`, `detail −= 1`.

### 5.9 `ImageTexture` ↔ `ShaderNodeTexImage` ●(noted, wiring-only here)

Engine (`advanced_features.h:195-230`): nearest-neighbor, clamp extension,
v-flip. Cycles default interpolation is linear and extension Repeat. Not a
procedural; out of pkg115's evaluator scope but the translator should pass
through `load_texture` and note the sampling-quality gap.

### 5.10 No-counterpart lists

**Blender nodes with NO engine counterpart (new evaluators needed):**
- `ShaderNodeTexWhiteNoise` — trivial once `util/hash.h` family is ported (§3.8).
- `ShaderNodeTexNoise` — the real one (Perlin + fBM stack); engine has nothing band-limited (§5.2).
- (Out of scope, record only: Gabor (4.3+, `svm/gabor.h`), Sky, Environment, IES, Point Density.)

**Engine procedurals with NO Blender node (keep, standalone-only):**
- `MarbleTexture`, `WoodTexture` (legacy Blender-Internal-style; no Cycles node) — keep factory strings, do not wire to the addon translator.
- `NoiseTexture` (sin-hash) — keep as legacy standalone string `"noise"`; consider aliasing to the white-noise port later.
- `SolidColor` — maps trivially to an RGB input, no node translation needed.
- Voronoi features `F1+F2`, `F2−F1` — standalone-only flags.

---

## 6. Recommended Stage-2 implementation order (smallest divergence first)

Each step is independently verifiable with a per-evaluator unit test
(engine `sample_texture()` vs values computed from the cited Cycles formulas)
plus a paired-still RTX check at the end.

1. **Coordinate/Mapping wiring** (no new math, unblocks everything): ✅ **DONE (partial, chunk 1)**
   unconnected-Vector → Generated default in the addon translator; UV-mode 3D
   coord = `(u,v,0)`; Normal mode → signed object-space; full-3D Mapping
   transform applied to the resolved coordinate (port `svm_mapping`, POINT
   first). Cite `mapping_util.h`, `tex_coord.h`.
   **Status:** addon default fixed, UV/Normal coord fixes in place. Full-3D
   Mapping deferred to next chunk.
2. **Checker** — ~10-line port of `svm_checker`. Immediate visual win. ✅ **DONE (chunk 1)**
3. **Gradient** — fix 4 formulas (quadratic clamp, spherical, quadratic
   sphere, radial phase) per `svm_gradient`; add addon enum map. ✅ **DONE (chunk 1)**
4. **Magic** — verbatim port of `svm_magic` (no dependencies); switch evaluator
   to RGB output. ✅ **DONE (chunk 1)**
5. **Hash family port** (`util/hash.h`: `hash_uint3`, `hash_float*`,
   `hash_int3_to_float3`) — enabler, plus **White Noise** evaluator (§3.8). ✅ **DONE 2026-06-11 (chunk 2)**
6. **Perlin + fractal stack + Noise node** — `noise.h` (BSD-3) `perlin_3d`/
   `snoise_3d`, `fractal_noise.h` five families, `noisetex.h` wrapper
   (distortion, color channels, normalize). Re-map factory `"musgrave"` with
   the 4.1 conversion (§5.8). ✅ **DONE 2026-06-11 (chunk 2)** — musgrave remap deferred to Stage 3 addon wiring
7. **Wave** — port `svm_wave` (depends on `noise_fbm` from step 6); extend
   factory params (directions, phase, dscale). ✅ **DONE 2026-06-11 (chunk 3)**
8. **Brick** — port `svm_brick` + `brick_noise`; 3D input; new params. ✅ **DONE 2026-06-11 (chunk 3)**
9. **Voronoi** — largest port: metrics + F1/F2/SmoothF1/DistToEdge/NSphere +
   fractal wrapper + normalize + multi-output mapping. ✅ **DONE 2026-06-11 (chunk 4, PR #445)**
10. **Addon translator + duplication removal + standalone CI example**
    (Stage 3/4 of the package spec). ✅ **DONE 2026-06-12 (chunks 5-6):** addon
    `load_procedural_texture` now routes all Blender procedural texture nodes
    (Noise, Voronoi, Wave, Brick, Checker, Gradient, Magic, Musgrave) through
    the engine's `create_procedural_texture` factory with Cycles-parity param
    vectors. Duplication removed — addon carries no private texture evaluators.
    C++ factory extended to accept full param vectors for Noise (Perlin-based,
    chunk 2), Wave (16 params: wave_type, bands/rings directions, phase_offset,
    detail_scale), and Brick (19 params: color1/color2 per-brick variation,
    mortar_smooth, bias, offset/squash frequencies). Tests added in
    `test_pkg115_addon_texture_translation.py` asserting param mappings match
    engine expectations. REMAINING: Blender-vs-Cycles paired-still visual
    (RTX `/verify`).

---

## 7. Acceptance hooks for Stage 2

- Per-evaluator parity tests: evaluate engine texture at fixed coordinates
  and compare against hand-computed values from the formulas in §3 (the
  formulas are deterministic; hash-based ones become testable once the same
  `util/hash.h` functions are ported).
- Visual: Blender material using Noise/Voronoi/Mapping/TexCoord rendered in
  Astroray vs Cycles, paired stills (RTX `/verify`), per the package spec.
- Standalone: existing `create_procedural_texture` scripts must keep working
  (factory params stay backward-compatible; new params appended).

---

## 8. Residual diagnosis 2026-06-12 — black gradient/magic spheres (paired-stills gate)

### Question investigated
Why did the GRADIENT (spherical) and MAGIC spheres render black on the addon
path while checker/voronoi/wave/brick were correct, and why did the earlier
diagnosis describe Cycles' gradient sphere as "bright-grey"?

### Cycles references (Blender 5.1 / main, projects.blender.org, Apache-2.0)
- `intern/cycles/kernel/svm/gradient.h::svm_gradient` — spherical:
  `r = max(0.999999 - len(p), 0)`. **Identical to our port** (advanced_features.h
  GradientTexture case 4).
- `intern/cycles/kernel/svm/magic.h::svm_magic` + `svm_node_tex_magic` — the
  node's **Color socket carries the raw float3** `(0.5-x, 0.5-y, 0.5-z)`;
  **Fac is `average(color)`**. Our MagicTexture collapsed the float3 to its
  average (greyscale) — fixed to per-channel output with color1/color2 as a
  per-channel tint (identity for the addon's black/white params).
- `intern/cycles/blender/util.h::mesh_texture_space` +
  `intern/cycles/blender/mesh.cpp` ATTR_STD_GENERATED loop —
  `generated = co * (0.5/texspace_size) - (texspace_location*(0.5/size) - 0.5)`,
  i.e. **bbox → [0,1]**. Confirmed empirically with an emission-shader probe
  (`Emission = TexCoord.Generated`, top-down camera): visible-cap RGB =
  `0.5 + 0.5*n̂` exactly. **Our per-object world-bbox bake matches the Cycles
  convention; the "[-1,1] or unnormalized" hypothesis is refuted.**

### Actual root cause (addon, not convention)
`load_procedural_texture` keyed its dedupe cache and texture names on
`id(node)`. `convert_node_material` iterates `bpy.data.materials` and works on
a **temporary `inline_shader_nodes()` tree freed after each material**; CPython
reuses the freed addresses, so a later material's texture node can carry the
same `id()` as an earlier material's (freed) node → silent cache hit → the
material binds the *previous* material's texture. Instrumented run (logged
`id(node)` per material): magic→bound brick's texture, noise→checker's,
wave→gradient's; only 4 textures created for 7 nodes. Victims shift run to run
with the allocator — explains "gradient + noise" in one session, "gradient +
magic" in another. A bound-but-foreign texture also gets the victim object's
bbox baked over it (`_generated_textures_by_material` records the alias), which
cross-contaminates the donor sphere's GENERATED frame — this is what erased the
gradient sphere's bright crescent.

Note: a *correct* spherical gradient on a [0,1]-generated sphere viewed from +z
IS mostly black with a thin bright crescent toward the bbox-min corner — the
fresh 64-spp Cycles still confirms this. "Bright-grey" came from the earlier
broken (2-spp) reference still.

### Fix
- Addon: cache/texture keys = `material_name + node.name` (stable, unique per
  conversion pass), `id()` fallback only for nameless unit-test stubs.
- Engine: MagicTexture per-channel RGB output (Cycles Color-socket semantics).
- Tests: `test_pkg115_addon_texture_translation.py::test_procedural_cache_key_identity_independent`,
  strengthened `test_pkg115_procedural_parity.py::test_magic_rgb_output`
  (hand-computed svm_magic reference at p=(0.3,0.4,0.5)).
