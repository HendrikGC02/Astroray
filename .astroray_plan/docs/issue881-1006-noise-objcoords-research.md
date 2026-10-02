# #881 Noise parity + #1006 Object coordinates: research note (2026-10-03, lane au-coords)

## Sources (all permissive)

| What | Source | License |
|---|---|---|
| Perlin 1D-4D, grad1/2/3/4, bi/tri/quad_mix, noise_scale1-4, snoise_* | Blender `intern/cycles/kernel/svm/noise.h` (v5.2 release branch; adapted from OSL) | BSD-3-Clause |
| fBM / multifractal / hetero / hybrid / ridged (templated per dimension) | `intern/cycles/kernel/svm/fractal_noise.h` | Apache-2.0 |
| Noise node: Scale on vector *and* W, distortion, colour seeds per dimension, Fac = value | `intern/cycles/kernel/svm/noisetex.h` (`svm_node_tex_noise`, `noise_texture_{1,2,3,4}d`, `random_float{,2,3,4}_offset`) | Apache-2.0 |
| `mix(a,b,t) = a + t*(b-a)`, `floorfrac` | `intern/cycles/util/math_base.h` | Apache-2.0 |
| Jenkins lookup3 `hash_uint{,2,3,4}`, `hash_float2_to_float` | `intern/cycles/util/hash.h` | Apache-2.0 |
| Object coordinate = inverse object transform of P | `intern/cycles/kernel/svm/tex_coord.h` `NODE_TEXCO_OBJECT` (`object_inverse_position_transform_if_object`; `NODE_TEXCO_OBJECT_WITH_TRANSFORM` when the node names another object) | Apache-2.0 |

The 3D path in `include/astroray/procedural_tex.h` (#1007, pkg115 port) already matched noise.h
line for line; it is unchanged (bit-identical, checked on 30 type x detail x distortion cases).

## #881 root causes (measured, not inferred)

Probe: 16 planes, Diffuse BSDF under a uniform white world (radiance = albedo, ~zero
variance), ortho camera, Cycles 5.2 CPU vs Astroray (build ar-1007 c5a26eac-equivalent),
32 spp, inner 60 % of each tile, min Pearson r over R/G/B.

1. **Fac into a colour socket gave the Color triple.** `get_base_color_texture` loaded Noise
   without a Fac variant; Cycles stores `value` on Fac. R matched (fit b = 0.999a + 0.000)
   while G/B were independent noise fields. This alone explains a low luminance correlation
   like the 0.73 in the issue. The op-VM path already broadcast `.x` (pkg293 `OP_SEP_COLOR`).
2. **1D / 2D / 4D (and W) were evaluated as 3D**: r = 0.003 / -0.12 / 0.09.
3. Not Noise: multifractal / ridged tiles exceed albedo 1 in Cycles; Astroray clamps the
   Diffuse albedo. On pixels with Cycles < 0.9 the slope is 1.00 and r >= 0.993.
   (Physics over look-parity: kept.)

The random offsets are tabulated (the #1007 table pins one fused multiply-add rounding of
`100 + h*100`). The 1D/2D/4D entries come from a Python port of `hash_uint`/`hash_uint2`
plus exact-rational FMA rounding to float32. The same generator reproduces all 15
pre-existing 3D entries bit for bit. The 2D/3D offsets are prefixes of the 4D ones
(component k always hashes `(seed, k)`).

Reference: `tests/fixtures/gen_issue881_noise_reference.py` evaluates Blender's own Noise
(Geometry Nodes, blenlib twin of the Cycles kernel) at 24 points x 28 cases (all dims x
types, distortion, normalize off). Engine vs Blender worst |diff| 1.1e-4 (2D hybrid);
1D/4D <= 6e-7 without distortion.

## #1006 design

The addon bakes `matrix_world` into the vertices, so the hit point is world-space. Fix:
bake `matrix_world^-1` (the stored pose: motion uses the shutter-open matrix) back onto
each triangle as per-vertex object-local positions (`set_objects_object_transform`,
mirroring #847's Generated bake). Because the transform is affine, the barycentric blend at
the hit equals `M^-1 P` exactly, the frame stays attached through `update_object_transform`,
and no per-hit state is added to the GPU hit buffer: a NaN-padded side table
`c_wfTexBinding.triObjectLocal` is read by `gpu_objectCoord` (per-hit procedurals and the
Object voxel bake, whose bbox is now object-local).

Instances: CPU never traverses instances (duplis are flattened, one frame per dupli). The
GPU two-level fast path is skipped for materials that read Object coordinates
(`_object_instanceable`), so they flatten too. Not covered: Texture Coordinate with an
explicit `object` (Cycles `NODE_TEXCO_OBJECT_WITH_TRANSFORM`), and the Normal output's
object-space normal. Both are follow-ups. Motion blur: the frame is interpolated with shutter-open barycentrics (as #847 Generated), reported as APPROXIMATED; fix tracked in #1034 (Terra review).
