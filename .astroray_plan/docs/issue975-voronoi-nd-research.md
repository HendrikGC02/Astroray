# #975 Voronoi Texture 1D / 2D / 4D: research note (2026-10-06)

Source: Blender Cycles, `blender-v5.2-release` (identical to `main` on 2026-10-06 apart from formatting),
`intern/cycles/kernel/svm/voronoi.h`, `util/hash.h`, `util/math_base.h`, `util/math_float{2,4}.h`.

| Function | File | License |
|---|---|---|
| `voronoi_f1`, `voronoi_smooth_f1`, `voronoi_f2`, `voronoi_distance_to_edge`, `voronoi_n_sphere_radius` (float / float2 / float4 overloads), `voronoi_distance`, `voronoi_distance_bound`, `fractal_voronoi_x_fx`, `fractal_voronoi_distance_to_edge`, `svm_node_tex_voronoi` | `kernel/svm/voronoi.h` | Apache-2.0; smooth F1 and distance to edge after Inigo Quilez 2013 (MIT) |
| `hash_pcg2d_i`, `hash_pcg4d_i`, `hash_int2_to_float2`, `hash_int4_to_float4`, `hash_int4_to_float3`, `hash_float_to_float3` | `util/hash.h` (PCG: Jarzynski & Olano, JCGT 2020) | Apache-2.0 |
| `smoothstep`, `mix` | `util/math_base.h` | Apache-2.0 |

Code: `include/astroray/procedural_tex.h` (the `#975` section, cited there). One host + device implementation, as for
the 3-D path (#1007): the GPU evaluates it per hit in `gpu_procTexEval` (`proc_tex_eval.cu`), out of line.

## What differs from the 3-D path

The 3-D port (pkg115) is kept as is (its output is bit-identical before and after this change). The 1D / 2D / 4D
code follows the 5.2 source, which differs from it in ways that matter:

* 1D hashes the float cell position (`hash_float_to_float`), 2D / 4D use PCG2D / PCG4D on int cells. Cell indices are
  ints (the 3-D port round-trips them through float).
* F1 searches with `voronoi_distance_bound` (squared / unrooted) and then evaluates the real distance once.
* Distance to Edge has its own fractal wrapper (`fractal_voronoi_distance_to_edge`: min-based, `max_amplitude`
  mixing); N-Sphere Radius is not fractal. The 3-D port routes both through the F1 wrapper (see findings below).
* The fractal wrapper has the `detail == 0 || roughness == 0` early-out and only runs Smooth F1 when `smoothness != 0`.
* 1D has no metric (`|b - a|`); `max_distance` for Normalize is `(0.5 + 0.5 r) * (F2 ? 2 : 1)` (1D), the metric
  distance of `(m, m[, m, m])` times that factor (2D / 4D), `0.5 + 0.5 r` (Distance to Edge).
* Distance / Radius are returned unclamped (Cycles' F2 / Manhattan reach 1.9, Smooth F1 dips below 0). The 3-D path
  keeps the pkg115 `[0,1]` clamp. N-Sphere Radius returns Radius (its Distance output is 0).
* Not computed: the Position / W outputs (no Astroray consumer reads them).

## Cycles reference (how the test table was made)

`vor_leg.py` (kept under `astra_run/batch-i/i5/`): headless Blender 5.2, Cycles CPU, an emission-only plane at
z = 0 seen by a top-down orthographic camera, Texture Coordinate > Object [> Mapping(Point)] > Voronoi > Emission
Color, film filter width 0.01 and 1 spp so every pixel is the node evaluated at its centre (x, y, 0). A W-linked
variant (W = object x) gives many 1D W values per render. Astroray is sampled at the same points
(`sample_named_texture`, `p = (u, v, 0)`; the tilt cases through `set_texture_mapping_matrix`).

Result, 79 cases (1D / 2D / 4D x F1 / Smooth F1 / F2 / Distance to Edge / N-Sphere Radius x metrics x Color x
randomness x smoothness x detail / roughness / lacunarity / normalize x tilted Mapping, 128 x 128 points each): the
maximum absolute difference to Cycles is 0.0 (float32-exact) in every case. In Blender (addon, CPU, 64 spp, emission
plane): per-channel mean ratio Astroray / Cycles >= 0.9990 in 69 of 70 cases; the exception is the flat colour
1D F1 Color (R channel 0.148 vs 0.1484, ratio 0.9965), the spectral RGB round trip of an emitter colour, not Voronoi.

## Findings outside this change (3-D path, left as is)

Measured against Cycles 5.2 on the same plane (`ref3d/`, `pointwise_3d.txt`):

* 3-D N-Sphere Radius returns the F1 distance, not the radius (mean ratio 1.56).
* 3-D F2 / Manhattan: distances above 1 are clamped to 1 by `voronoi_texture` (ratio 0.90); Smooth F1 negatives too.
* 3-D Distance to Edge with detail > 0: the F1-style fractal wrapper, Cycles uses `fractal_voronoi_distance_to_edge`
  (ratio 1.12).
