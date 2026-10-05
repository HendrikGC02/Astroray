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

## Review follow-ups (Opus Cycles-parity review, 2026-10-06)
A pass keeps the ray's direction but Astroray restarts it at the sheet, whereas Cycles
keeps origin/direction/tmax and moves only tmin (`shade_surface.h`). Everything that was
keyed on "bounce" or on the ray origin needed a fix (CPU `raytracer.h`, GPU
`stage_advance_device.cuh`; tests `tests/test_issue1033_review_fixes.py`):
- Last real vertex: CPU `vertexOrigin`/`passPrev`; GPU `GPUWavefrontState.pass_dist`
  (cumulative hit distance, parked by the shade stage on a pass, read and zeroed by the
  intersect stage; touched only when the scene has a Principled alpha < 1). Gives the
  MIS light-pdf origin (`origin - dir * pass_dist`), cumulative Ray Length
  (`shader_data.h`), and the far clip behind a sheet (`tmax = far*zInv - pass_dist`;
  near clip stays camera-segment only).
- MIS state (`wasSpecular`, `bsdfPdfPrev`, `misNormalPrev`, `envNeeSampledPrev`, GPU
  `was_specular` / `path_bsdf_pdf` / `path_mis_n*` / `env_nee_sampled_prev`) is untouched by
  a pass (Cycles `mis_ray_pdf` / `MIS_SKIP` survive `LABEL_TRANSPARENT`).
- GPU product-carrying media streams (world-fog free flight, grid tracker) salt with
  `bounce + passes` (Cycles advances `rng_offset` by `PRNG_BOUNCE_NUM` on a pass,
  `path_state.h`) and the grid `r_u` reset gates on `pass_dist == 0`. The segment-NEE /
  lamp-Tr / shadow-ray streams stay keyed on `bounce`: their draws are summed with other
  segments' terms, never multiplied into the path throughput, so replaying them across a
  pass is correlated but unbiased.
- Photon split: a bounce-0 hit behind a pass starts no chain (the gather only reaches the
  first geometric hit), so the caustic is path traced there; CPU and GPU identical.
- Guides: GPU denoise guides gate on `pass_dist == 0` (first hit, as the CPU). Cycles'
  opacity-weighted blend is a follow-up.
- Cryptomatte: no credit on the transparent-lobe sample (`!transparentPass` / `!tp`).
- CPU `coverageAlpha`: a surface with alpha < 1 covers the film with probability alpha,
  else the camera ray passes through (matches the GPU's miss-coverage count).
- Shadow rays keep their own `maxHops = 8` (CPU `shadowTransmittance`) and the GPU's
  unlimited shadow walk saturates at 31, instead of sharing the transparent budget as in
  Cycles: tracked in a follow-up issue.
