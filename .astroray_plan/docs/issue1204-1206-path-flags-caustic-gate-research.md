# #1204 / #1206 — Light Path flags after transmission, caustic gate — Research

## Source
No paper: Cycles path-state bookkeeping and closure setup, ported for parity (owner: Light Path flags
and caustic toggles follow Cycles).

## Reference implementation
- **Repo:** https://github.com/blender/blender, tag `v5.2.0` (`intern/cycles`), Apache-2.0.
  Semantics ported, no code copied.
- `kernel/integrator/path_state.h:143-235` `path_state_next`: `visibility = PATH_RAY_VISIBILITY_NONE`
  every non-transparent bounce (transparent returns early and keeps it). TRANSMIT for a transmission;
  then `LABEL_DIFFUSE` -> DIFFUSE (+ sticky `PATH_RAY_DIFFUSE_ANCESTOR` flag), `LABEL_GLOSSY` -> GLOSSY,
  else SINGULAR -> GLOSSY + `PATH_RAY_SINGULAR`. This runs for reflections AND transmissions.
  Volume scatter: VOLUME_SCATTER only.
- `kernel/integrator/shade_surface.h:773,788` passes the RAW `path.visibility` to
  `surface_shader_eval`, so `svm/light_path.h:33-36` (Is Diffuse / Is Glossy Ray) and the closure
  setup in `svm/closure.h` see DIFFUSE/GLOSSY on a transmission ray. `path_state_ray_visibility`
  (path_state.h:262-275) strips them only for object ray visibility, not for shading.
- `kernel/svm/closure.h` `__CAUSTICS_TRICKS__`: `reflective_caustics = caustics_reflective ||
  !(ray_visibility & PATH_RAY_VISIBILITY_DIFFUSE)` (refractive alike). `ray_visibility` is the
  previous bounce's visibility, so the gate is "the previous non-transparent scatter was diffuse"
  (reflect or transmit). `PATH_RAY_DIFFUSE_ANCESTOR` is set but never read by these gates.
  - Principled (:257-470): metallic closure dropped if !reflective (weight still `*= 1-metallic`);
    coat closure and its layering attenuation dropped if !reflective (coat tint kept);
    transmission: dropped only if both off, else `generalized_schlick_setup`
    (bsdf_microfacet.h:111-125) zeroes the reflection tint (!reflective) or transmission tint
    (!refractive); weight still `*= 1-transmission`; specular closure and its layering
    attenuation dropped if !reflective. Thin-wall glass: `bsdf_thin_glass_setup(..reflective,
    refractive..)`.
  - Conductor / Glossy (:565, :669): closure dropped if !reflective. Refraction (:742): dropped if
    !refractive. Glass (:785): dropped if both off, else tints as above. Hair, sheen, diffuse,
    translucent, transparent: never gated.
- Labels: `bsdf_diffuse.h:72,124` (REFLECT|DIFFUSE, TRANSMIT|DIFFUSE),
  `bsdf_principled_hair_chiang.h:453` (GLOSSY | REFLECT or TRANSMIT), microfacet GLOSSY/SINGULAR.

## Corrections to earlier notes
- `pkg201-item-e-caustic-toggle-research.md` called `PATH_RAY_VISIBILITY_DIFFUSE` sticky. It is not:
  `path_state_next` resets visibility each bounce. Floor -> mirror -> glass -> light is kept by Cycles
  with refractive caustics off (the glass vertex's previous bounce is the mirror).
- `issue1178-sampled-lobe-label-research.md` "Differences": a translucent bounce now sets DIFFUSE.

## What we reproduce
- `lightpath::next_surface(c, cat, singular, label, transparent)`: a transmission ORs DIFFUSE
  (`label & DIFFUSE`, not singular) or GLOSSY (everything else). Is Glossy Ray = 1 behind smooth and
  rough glass; Is Diffuse Ray = 1 behind a translucent sheet.
- Gate = previous scatter's DIFFUSE visibility (CPU: `lpc.flags & LPF_DIFFUSE` via `rec.lightPath`;
  GPU: per-slot `ray_vis_diffuse`, cleared on volume scatter, kept across transparent passes),
  combined with the toggles into `HitRecord::causticGate` / `GHitRecord::causticGate`
  (`lightpath::caustic_gate`). Materials drop gated closures at setup, as Cycles does:
  Principled lobes (metallic, coat, specular, thin-glass R/T; transmission side-gated), Metal,
  ThinGlass. NEE at the vertex therefore sees the gated BSDF too.
- Delta samples on a gated side are still culled in the integrator (Dielectric, Mirror, smooth
  metal, smooth Principled glass): exact for a singular closure.
- Metal, ThinGlass and Principled Hair `sample()` report `BSDF_LABEL_GLOSSY` (CPU + GPU), so a
  NormalMapped / TwoSided wrapper classifies them as glossy.

## Differences from the reference
- Half-gated glass (one toggle off): Cycles zeroes a tint and stops sampling that side; Astroray
  zeroes that side's eval and keeps the sampling pdf. Same expectation, more variance. The
  multi-GGX energy-compensation term still uses the ungated tints (second order).
- Principled emission under a gated coat keeps the coat attenuation (Cycles drops it with the coat).
- Disney (legacy fallback) and Phong do not honour the gate; the addon never exports them.

## Integration in Astroray
- `include/astroray/light_path.h`, `include/raytracer.h` (HitRecord, pathTraceSpectral, the two
  other next_surface sites), `plugins/materials/{principled,metal,thin_glass,principled_hair}.cpp`.
- GPU: `include/astroray/gpu_types.h` (GHitRecord), `include/astroray/gpu_materials.h`,
  `include/astroray/gpu_wavefront_state.h`, `src/gpu/wavefront/{stage_advance_device.cuh,
  stage_advance.cu, stage_volume_hetero.cu, stage_init.cu, wavefront_state.cu,
  shading_inputs_eval.cu}`.
- Tests: `tests/test_issue1204_1206_path_flags.py`.
