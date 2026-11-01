# #1178 / #1198 — Bounce class from the sampled closure label — Research

## Source
No paper: this is Cycles' path-state bookkeeping, ported for parity.

## Reference implementation
- **Repo:** https://github.com/blender/blender, tag `v5.2.0` (`intern/cycles`)
- **License:** Apache-2.0 (Cycles kernel). Compatible with Astroray's licence; semantics are ported, no code is copied.
- **Files read:**
  - `kernel/types.h:329-342`: `ClosureLabel` bits: `LABEL_TRANSMIT=1, REFLECT=2, DIFFUSE=4, GLOSSY=8, SINGULAR=16, TRANSPARENT=32, ...`.
  - `kernel/integrator/path_state.h:143-217` `path_state_next(label)`: a `LABEL_REFLECT` scatter increments
    `diffuse_bounce` if `label & LABEL_DIFFUSE`, else `glossy_bounce` (singular reflections count as glossy);
    a transmit scatter increments `transmission_bounce`. Then `LABEL_DIFFUSE` sets visibility DIFFUSE and the
    sticky `PATH_RAY_DIFFUSE_ANCESTOR`; `LABEL_GLOSSY` sets GLOSSY; otherwise SINGULAR (glossy visibility).
  - Labels returned by the closures: `bsdf_diffuse.h:72` (REFLECT|DIFFUSE), `:124` translucent (TRANSMIT|DIFFUSE),
    `bsdf_sheen.h:101,109` (REFLECT|DIFFUSE), `bsdf_microfacet.h:916-917` (REFLECT or TRANSMIT | GLOSSY or SINGULAR).

## What we reproduce
- The label is a property of the SAMPLED closure, not the material. A Principled BSDF that samples its
  diffuse lobe makes a diffuse bounce (counts against `max_diffuse_bounces`, sets the diffuse-ancestor flag,
  Light Path "Is Diffuse Ray" = 1); its specular/metallic/coat/glass lobes make glossy bounces.
- `BSDFSample` / `BSDFSampleSpectral` (CPU) and `GBSDFSample` (GPU) carry `label` (`BSDF_LABEL_DIFFUSE=4`,
  `BSDF_LABEL_GLOSSY=8`, the Cycles bit values; 0 = not reported). `lightpath::bounce_class` (light_path.h,
  HD) classifies: geometric transmission -> 2, `isDelta` (singular) -> 1, else the label, else the material
  class fallback (`Material::isGlossy` / `gpu_material_is_glossy`).
- Principled: Diffuse, Sheen, Subsurface (Astroray's Lambertian stand-in for the SSS exit) and Translucent
  lobes report DIFFUSE; every other lobe GLOSSY. Add/Mix (CPU `ClosureNodeMaterial`, GPU closure tree)
  label an unlabelled child sample by the PICKED child's class.

## Differences from the reference
- TRANSMIT and SINGULAR are not carried in `label`: transmission stays the existing geometric side test and
  singular is `isDelta`, which agree with Cycles' labels for every Astroray closure.
- A diffuse transmission (Translucent lobe) still classifies as transmission without setting the diffuse
  ancestor / Is Diffuse Ray; Cycles sets both for TRANSMIT|DIFFUSE. Left as is (no reported case).
- Materials that do not report a label keep the old material-class behaviour; decorators without an
  `isGlossy` forward (NormalMapped, TwoSided) still fall back to `false` for a non-Principled inner.
- Direct-light AOV split (`neePass` at bounce 0) still uses `isGlossy()`: Cycles splits that by closure
  eval, not by a sampled label; out of scope.

## Integration in Astroray
- CPU: `include/raytracer.h` (structs, base sampleSpectral copy, three classification sites),
  `plugins/materials/principled.cpp` (`lobeLabel`), `include/astroray/closure_mix.h`.
- GPU: `include/astroray/gpu_types.h` (field), `include/astroray/gpu_materials.h` (`gpu_principled_sample`),
  `src/gpu/wavefront/stage_advance_device.cuh` (tree sampler, firstCat lock, per-type caps, caustic gate),
  `src/gpu/wavefront/shading_inputs_eval.cu` (`gpu_lpAdvance`).
- Tests: `tests/test_issue1178_sampled_lobe_label.py`.
