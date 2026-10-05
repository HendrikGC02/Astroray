# #1033 - transparent pass-throughs are not bounces

Source (Apache-2.0): Blender Cycles `src/kernel/integrator/path_state.h`
`path_state_next`, `integrator/intersect_closest.h`, `integrator/shade_surface.h`
(`integrate_surface_terminate`), `scene/integrator.cpp`.

## Cycles semantics
- `LABEL_TRANSPARENT` early-returns in `path_state_next`: flags kept, only
  `transparent_bounce` is incremented. `bounce`, `diffuse/glossy/transmission_bounce`
  are untouched, so the clamp class (`bounce > 0` -> indirect) and `max_bounces`
  ignore the pass.
- `transparent_bounce + 1 >= transparent_max_bounce` sets
  `PATH_RAY_TERMINATE_ON_NEXT_SURFACE`: the NEXT surface hit evaluates emission
  then terminates (no NEE, no continuation).

## Verified against Blender 5.2 Cycles (CPU, headless)
3 stacked Transparent-BSDF sheets (small, shadow ray tilted around them) in front of
a sun-lit diffuse wall: wall = 0 for `transparent_max_bounces` = 0, 1, 2, 3 and lit
(0.54) for 4 and 8. I.e. the surface after the T-th pass is terminated.

## Astroray implementation
- CPU `pathTraceSpectral` / `pathTraceSpectralCaustic`: `transparentPass` (existing
  `is_transparent_pass`) -> `--bounce` (nets the loop's `++bounce`), skips per-type
  counters, caustic cull, pass-category lock; count = `lpc.transparentDepth`;
  terminate-on-next-surface after the emission block. Camera clip planes apply to the
  camera segment only (`primarySeg`).
- GPU shade: `tp` (noinline `gpu_isTransparentPass`, gated by `c_wfTransparentLimit`,
  on only when the scene has a Principled alpha < 1): `state.bounce` not advanced,
  count in the existing `lp_state` bits 27-31 (saturating 31), per-type / caustic /
  AOV-lock skipped. Intersect: terminate-on-next-surface after emission. Host pass
  plan grants `limit + 1` (31 + 1 unlimited) extra passes.
- Light Path `Ray Depth` no longer subtracts `transparentDepth` (the bounce counter
  already excludes it).

## Known gaps
- Shadow-ray transparent walks keep their own `maxHops = 8` (Cycles counts shadow
  hits against the same transparent budget).
- GPU count saturates at 31: a limit above 31 never fires (#1047 item 4).
- Addon viewport/exporter pass `min(transparent_bounces, depth)`; Cycles' limit is
  independent of `max_bounces`.
