# #991 Light Path node: research note (2026-10-03, lane N1)

## Sources (Apache-2.0, Blender Cycles, `main`)

* `intern/cycles/kernel/svm/light_path.h` `svm_node_light_path`: Is Camera / Shadow / Diffuse /
  Glossy / Transmission / Volume Scatter read the ray **visibility**; Is Singular / Is Reflection
  read the path **flag**; Ray Length = `sd->ray_length`; Ray Depth = path bounce, **+1 for shadow
  and emission evaluation** ("effectively one bounce further"); Diffuse / Glossy / Transmission /
  Transparent Depth = the per-type counters.
* `intern/cycles/kernel/integrator/path_state.h` `path_state_next`: a transparent bounce keeps the
  flags; a surface bounce clears REFLECT/SINGULAR, sets REFLECT + (DIFFUSE | GLOSSY | GLOSSY+SINGULAR)
  or TRANSMIT, increments diffuse/glossy only on reflection and transmission_bounce on transmission;
  a volume scatter sets VOLUME_SCATTER only. `path_state_ray_visibility` strips DIFFUSE/GLOSSY from a
  transmission ray. Camera rays start with visibility CAMERA.
* `kernel/svm/closure.h` `svm_node_mix_closure`: Mix Shader weights (1-f)A + fB, f clamped to [0,1].
  With a boolean Fac exactly one child carries weight, so the Mix is a per-ray closure switch.
* Shadow evaluation (`integrate_transparent_surface_shadow`) runs the surface shader with
  `PATH_RAY_SHADOW`; light-sample emission (`light_sample_shader_eval`) with `PATH_RAY_EMISSION`
  (no visibility bit set).

## Astroray mapping

* Shared service `include/astroray/light_path.h` (HD, single source): `PathContext`,
  `light_path_output`, `next_surface`, `next_volume`, `shadow_context`, `emission_context`, a 32-bit
  GPU pack, and `resolve_switch` for the device side table. Re-hostable by the per-hit graph
  interpreter (architecture memo 2026-10-03, option B).
* Path state is live state only: CPU `pathTraceSpectral` / `pathTraceSpectralCaustic` locals; GPU
  `GPUWavefrontState.lp_state` (path state, not the hit buffer) + `bounce` + the parked hit `t`.
* Bounce class: Astroray has no per-closure lobe labels; the existing pkg201 classifier (transmitted
  by geometric sign, glossy if delta or the material `isGlossy()`, else diffuse) is shared by both
  backends. It is per-material (a Principled bounce counts as glossy), so Is Diffuse / Is Glossy Ray
  and Diffuse / Glossy Depth are reported APPROXIMATED. Transparent Depth is 0 (a Transparent pass is
  a transmission bounce here): reported. Portal Depth: unsupported (reported).
* Values feed the op-VM through `OP_SHADING` (`SH_LIGHT_PATH + output`), so a Ray Length -> Ramp
  base colour runs per hit on CPU (`ProgramTexture::valueAtHit`) and GPU (`<HasProgram>` shade block).
* Mix Shader with a boolean Light Path Fac -> `LightPathMixMaterial` (CPU) / a `GLightPathSwitch`
  side-table entry (GPU). Contexts: surface hits resolve with the hit's path state (CPU after
  `bvh->hit`, GPU in the intersect stage before emission, bucketing and the parked hit); shadow rays
  with the shadow context (CPU `shadowAlpha`, GPU `gpu_shadow_transmittance`); emission evaluation
  (NEE light samples, light list) sees child A, which is what every boolean output selects there.
  A Transparent child becomes Principled Alpha 0 (Cycles: Alpha is a mix with a white Transparent
  BSDF), so it passes camera rays and casts no shadow through the existing pkg253 path.
* Reported limits: a Light Path Fac through other nodes or from Ray Length / a depth; Is Singular /
  Is Reflection as Fac on shadow rays (Cycles reads the parent path flag there); a tinted Transparent
  child; a switch nested under another Mix / Add Shader. After a camera ray passes a camera-hidden
  surface Astroray has counted a bounce, so a second surface behind it reads Is Camera Ray = 0
  (Cycles keeps the camera flag through transparent bounces).
