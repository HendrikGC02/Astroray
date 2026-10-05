# #1073 / #1047 item 3 - shadow-ray transparent budget and Light Path context

Source (Apache-2.0), Blender Cycles `intern/cycles/kernel/`:
`integrator/intersect_shadow.h` (`integrate_shadow_max_transparent_hits`,
`integrate_intersect_shadow_transparent`), `bvh/intersect_filter.h`
(`bvh_shadow_all_anyhit_filter`), `integrator/shade_shadow.h`
(`integrate_transparent_surface_shadow`), `integrator/shade_surface.h`
(`integrate_direct_light_shadow_init_common`), `svm/light_path.h`.

## Budget (#1073)
- `shadow_path.transparent_bounce` is copied from `path.transparent_bounce` when the shadow
  ray is created (`integrate_direct_light_shadow_init_common`).
- `max_transparent_hits = max(transparent_max_bounce - shadow_path.transparent_bounce, 0)`.
- `bvh_shadow_all_anyhit_filter`: a surface whose shader has `SD_HAS_TRANSPARENT_SHADOW`
  increments `num_transparent_hits`; `num_transparent_hits > max_transparent_hits` zeroes the
  ray throughput (blocked). A shader without transparent shadows blocks immediately.
  So a shadow ray crosses exactly `max_transparent_hits` transparent surfaces; the next blocks.
- `shade_shadow.h` increments `shadow_path.transparent_bounce` per accepted hit (matters only
  for rays re-intersected after `INTEGRATOR_SHADOW_ISECT_SIZE` recorded hits).

Measured on Blender 5.2 Cycles (CPU, headless, `.../astra_run/batch-g/lane-g1/cycles_probe.py`):
- N sheets between floor and sun, camera sees the floor (path pass count 0): lit iff
  limit >= N (N=3: 0,2 black / 3,4 lit; N=2: 1 black / 2 lit).
- 3 sheets between camera and wall (3 camera passes + 3 shadow hits): black for limit
  3, 4, 5; lit for 6, 8.

Astroray: CPU `shadowTransmittance(..., maxTransparentHits)` counts transparent hits after
the `Tr < 1e-3` early-out and blocks past the budget (-1 = unlimited, hop cap 1024 = Cycles'
UI ceiling, exhausted = blocked). The budget is `Renderer::shadowTransparentHits(depth)`,
depth = `lpc.transparentDepth` at the NEE vertex (0 for the integrators that do not track
passes). GPU: `gpu_shadow_transmittance(..., maxHits)`; `stageShadowKernel<..,HasAlphaShadow>`
computes `c_wfTransparentLimit - lane6`, lane 6 = lp_state bits 27-31 parked pre-advance by
the shade-stage lamp NEE and the intersect-stage volume-segment record.
Not covered: GPU env-NEE shadow records and the immediate (flat/dense) NEE walk never walked
transparent occluders (binary occlusion), unchanged; a GPU limit above 31 saturates (#1047
item 4).

## #1047 item 3: Is Singular / Is Reflection on a shadow ray
The issue says Cycles reads them from the parent path_flag. It does not (5.2 source and
measurement): `shade_shadow.h` calls
`surface_shader_eval(kg, state, shadow_sd, nullptr, PATH_RAY_VISIBILITY_SHADOW, PATH_RAY_FLAG_NONE)`
and `svm_node_light_path` reads Is Singular / Is Reflection from `path_flag` (= NONE) and the
Is Camera / Shadow / Diffuse / Glossy / Transmission / Volume Scatter outputs from the
visibility mask (= SHADOW). Probe (sheet `Mix(Fac = <output>, A = black diffuse, B =
Transparent)`, floor seen directly and via a singular mirror reflection): Is Shadow Ray lit
(0.89 / 0.81), Is Singular Ray and Is Reflection Ray both blocked (0.0007 / 0.060; the 0.06 is
mirror-bounce indirect light, equal for both). The counters do come from the parent
(`shadow_path` copies diffuse/glossy/transmission/transparent bounce; a Math(Glossy Depth > 0.5)
Fac is lit under the mirror, blocked directly), but only boolean Light Path outputs can drive
a Mix switch here (`light_path.h is_boolean_output`), so that path is unreachable.
Astroray's shadow context (`LPF_SHADOW` only) already matches; pinned by
`tests/test_issue1073_shadow_transparent_budget.py`.
