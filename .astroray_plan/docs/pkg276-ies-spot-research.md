# pkg276 — IES x spot composition vs Cycles: research + measured A/B

## Sources (no paper; the reference IS the Cycles implementation)
- **Repo:** Blender 5.2 Cycles, `blender-v5.2-release` branch; kernel sources also
  ship in the Blender 5.2 install (`5.2/scripts/addons_core/cycles/source/kernel`).
- **License:** Apache-2.0 (SPDX headers in every file) — compatible with Astroray.
- **Functions ported / mirrored:**
  - `intern/cycles/util/ies.cpp` — `IESFile::parse` (factor = multiplier x ballast x
    ballast-lamp factor x 4*pi/177.83), `IESFile::process_type_c` (h symmetry expansion),
    `IESFile::process` (`angle *= M_PI_F / 180.f`).
  - `intern/cycles/kernel/util/ies.h` — `kernel_ies_interp`, `interpolate_ies_vertical`
    (Catmull-Rom in v then h; out-of-range -> 0; wrap flags).
  - `intern/cycles/util/math_base.h` — `cubic_interp`, `smoothstepf`, `inverse_lerp`.
  - `intern/cycles/kernel/svm/ies.h` — `svm_node_ies`: `fac = strength * interp(h, v)`,
    `v = safe_acosf(-vector.z)`, `h = atan2f(vector.x, vector.y) + M_PI_F`.
  - `intern/cycles/scene/shader_nodes.cpp` `IESLightNode` Vector socket =
    `LINK_TEXTURE_INCOMING`; `scene/shader_graph.cpp` resolves it to Geometry:Incoming
    through a world->object NORMAL VectorTransform (`kernel/svm/vector_transform.h`,
    `object_inverse_normal_transform` = `transform_direction_transposed`). For a lamp
    `sd->object = klight->object_id` and `wi = -ray_D` (`kernel/light/sample.h`
    `light_sample_shader_eval_forward`), so the vector is the light->lit-point direction
    in light-object space.
  - `intern/cycles/kernel/light/spot.h` — `spot_light_attenuation` =
    `smoothstepf((ray.z - cos_half_spot_angle) * spot_smooth)` on `spot_light_to_local`.
  - `intern/cycles/scene/light.cpp` — `SpotLight::copy_to_kernel`:
    `cos_half_spot_angle = cos(angle/2)`, `spot_smooth = 1/((1 - cos_half) * smooth)`;
    `PointLight::copy_to_kernel`: radius 0 -> area 4 -> `eval_fac = 1/(4 pi)`.
  - `intern/cycles/blender/light.cpp` — `set_angle(spot_size)`, `set_smooth(spot_blend)`.

## Composition (Cycles, radius-0 point/spot, Diffuse plane)
`L = rho/pi * P * (1/(4 pi)) * spot_atten(cos) * ies_strength * interp(h, v) * cos_i / d^2`
(light shader emission x `eval_fac` x `strength`, pdf = d^2). Multiplicative, same
order as Astroray's `intensity * 1/(4 pi) * falloff * angleFalloff * iesModulation`.

## Cycles quirk reproduced on purpose
The wrap tests are float32: `h_high > M_2PI_F - 1e-7f`. 1e-7f is below the ulp at
2*pi (and pi), so `M_2PI_F - 1e-7f == M_2PI_F` and a 0..360 table has
`h_high == M_2PI_F` -> **wrap_h = false**; likewise a 0..180 vertical range does not
set wrap_vhigh. Ignoring this put the reference 1.8 % off Cycles in the 330-360 deg
sector; with it, the match is exact. `ies_eval.h` evaluates the same float32
expression, so CPU and GPU reproduce it.

## Controlled scene (benchmarks/cycles-parity/ies_spot/)
Spot 60 deg / blend 0.15 (and POINT), 100 W, radius 0, at (0.25, -0.15, 2.0), spun
30 deg about Z; grey Diffuse (0.5) plane z=0; black world; top-down 30 deg camera at
z=6; 200x200; Cycles CPU 64 spp, BOX 1 px filter, clamps off. Profiles: synthetic
asymmetric type C `asym_profile_lm63` (h 0..360/30, v 0..90/5; azimuth lobe
`1 + 0.6 cos(h-40) + 0.3 cos(2h-170)` has no mirror axis), the pkg259 wall-washer
(h 0..315 -> Cycles appends 360), a quadrant (h 0..90) profile in the tests.

## Measured: Cycles 5.2 vs numpy reference (`ies_reference.py`)
| leg | total | 1-deg annuli (min..max) | 15-deg azimuth sectors |
|---|---|---|---|
| SPOT, no IES | 1.0000 | 0.9999..1.0002 | 1.000 all |
| SPOT + asym | 1.0000 | 0.9999..1.0002 | 1.000 all |
| POINT + asym | 1.0000 | 0.9999..1.0001 | 1.000 all |
| SPOT + wall-washer | 1.0000 | 0.9999..1.0002 | 1.000 all |

The reference is a faithful Cycles model (frame convention and float32 quirk included).

## Measured: Astroray CPU (origin/main 030fbd14) vs reference — the localised factors
| factor | evidence | size |
|---|---|---|
| **Addon cone mapping** — `inner = outer*(1-blend)` (angle space) vs Cycles cos-space `cos_inner = cos_half + (1-cos_half)*blend` | SPOT no-IES annuli 26/27/28/29 deg: 0.78/0.53/0.34/0.25 (core 0.91) | falloff starts at 25.5 deg instead of 27.6 deg |
| **IES frame** — arbitrary ONB off the axis (spot) / fixed (0,-1,0) axis (point) vs Cycles light-object frame | azimuth sectors 0.29..3.0 (spot asym), 0.42..9.4 (point asym, which is also tilted 90 deg in Blender Z-up) | rotation of the lobe |
| **IES interpolation** — bilinear + clamp vs Cycles Catmull-Rom + zero outside + h-symmetry expansion | radial 1.03..1.27 at the g(v) trough (spot asym) | up to 27 % at troughs |
| **Delta-light MIS weight** (NOT IES) — radius-0 point/spot `LiSample.isDelta` unset, so the power heuristic weights NEE by `1/(1+(cos_i/pi)^2)` although BSDF rays can never hit a delta light | core 0.910..0.928 == analytic weight; N equal lights: 0.910 / 0.722 / 0.397 for N = 1/2/4 | whole light, grows with light count |
| Raster divisor `(res-1)` (camera, not light; deferred by pkg212) | with the delta weight divided out and the reference sampled at `res-1`, the Cycles-mapped no-IES spot matches 1.000..1.005 in every 1-deg annulus | ~0.5 px image shift |

Not localised here (left as-is, noted): ballast / ballast-lamp factors ignored by the
Astroray parser (1.0 in all test files); TILT=INCLUDE files; photometric types A/B are
read as type C. Separate finding (not fixed): radius>0 point/spot NEE returns an
area-measure pdf `1/(4 pi r^2)` against point-intensity emission, so brightness scales
with `4 pi r^2` (measured 0.125x at r=0.1, 0.74x at Blender's default 0.25).

## Decisions
- One Cycles-port lookup, shared host/device: `include/astroray/ies_eval.h`
  (`interp` = `kernel_ies_interp`, `evalLocal` = `svm_node_ies` angles). `IESProfile`
  stores the Cycles packed layout after `process_type_c`; CPU and GPU call the same code.
- Frame: the addon passes `matrix_world.to_3x3()` columns as `light_frame`; the engine
  computes `local = (d.X, d.Y, d.Z)` (normal transform, exact for scaled lights too).
  Without a frame: spot uses local -Z = axis, point keeps its old (0,-1,0) axis.
- Cone: fixed in the addon mapping (the engine has no blend input); the engine's
  smoothstep in t is then algebraically the Cycles field (test
  `test_reference_cone_mapping_equals_cycles_field`).
- Gates sample the reference at the engine's `(res-1)` raster positions so they measure
  the light, not the camera.
