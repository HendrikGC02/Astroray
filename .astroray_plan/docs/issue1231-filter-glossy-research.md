# #1231 research: v2_viewport Grid100k witness is Cycles Filter Glossy

**Verdict.** The +2.5 % R / +2.1 % G / +1.1 % B Grid100k bias is not in the grid's
Principled BSDF. Cycles blurs the gold sphere's GGX lobe on paths that reach it
after a diffuse bounce (Filter Glossy, `scene.cycles.blur_glossy = 1.0`, the Blender
default and this scene's value). Astroray stores `filterGlossy`
(`include/raytracer.h` `setFilterGlossy`) but never reads it, on either backend.
With Filter Glossy off on the Cycles leg, the witness passes Welch-1b on CPU and on GPU.

## Evidence (current batch build b1101c, 64 spp, 8 seeds 278..11027, witness ROI)

Welch-1b (alpha 0.05, tile 8, delta_rel 0.01), Holm-rejected tiles / tests:

| Astroray leg | Cycles leg | rejects | ROI mean ratio R/G/B |
|---|---|---|---|
| CPU | audit stack (blur_glossy 1.0) | 1749/6720 FAIL | 1.0251 1.0213 1.0106 |
| GPU | audit stack (blur_glossy 1.0) | 1761/6720 FAIL | 1.0250 1.0213 1.0106 |
| CPU | blur_glossy 0 | **0/6720 PASS** | 0.9987 0.9979 0.9978 |
| GPU | blur_glossy 0 | **0/6720 PASS** | 0.9986 0.9979 0.9978 |
| GPU | CPU | 0/6720 PASS | 0.9999 1.0000 0.9999 |

Changing `filter_glossy` on the Astroray leg leaves its frames bit-identical (max |diff| 0).

Bisect (CPU, 4 seeds; Astroray/Cycles ratio in the ROI, then the band under the sphere):

| variant | ROI | contact band (rows 250+, cols 240-400) | sphere top (camera-direct) |
|---|---|---|---|
| baseline | 1.025 1.021 1.010 | 1.134 1.117 1.065 | 1.000 1.000 0.999 |
| all bounce caps 64 | 1.025 1.021 1.010 | 1.134 1.116 1.064 | same |
| all bounce caps 1 | 1.015 1.014 1.007 | 1.069 1.064 1.043 | same |
| sphere Metallic 0 (grey dielectric) | 1.004 1.004 1.004 | 1.025 1.026 1.026 | same |
| sphere base colour grey 0.8 (metal) | 1.022 1.022 1.022 | 1.121 1.121 1.121 | same |
| grid -> diffuse (audit control leg, seed 7) | 1.036 1.032 1.016 | | |
| **Cycles blur_glossy 0** | **0.998 0.998 0.998** | **0.997 0.996 0.995** | same |

The bias is local: about 1.00 on far grid columns and up to +15 % in the grid and sphere
bottom near the contact. It follows the metal sphere: a grey metal gives the same
achromatic +12 %. The red lean is only gold's colour. Camera-direct sphere pixels match,
because the camera ray has `min_ray_pdf = FLT_MAX`, so Cycles does not blur them. The
grid-material control fails the same way, so none of the 33 Principled sockets on the
grid is implicated.

## Cycles v5.2.0 mechanism (Apache-2.0; `intern/cycles/`)

- `scene/integrator.cpp:269`: kernel `filter_glossy = 1/blur_glossy` (`FLT_MAX` when 0).
- `kernel/integrator/path_state.h:62`: `min_ray_pdf = FLT_MAX` at path start.
- `kernel/integrator/shade_surface.h:608-612`: after each non-transparent BSDF sample,
  `min_ray_pdf = fminf(unguided_bsdf_pdf, min_ray_pdf)`. This is the sampled
  direction's mixture pdf.
- `kernel/integrator/surface_shader.h:184-213`: at the next hit, before any eval, sample
  or NEE, if `blur_pdf = filter_glossy * min_ray_pdf < 1`, then
  `blur_roughness = sqrtf(1 - blur_pdf) * 0.5f` and `bsdf_blur` runs on every closure.
- `kernel/closure/bsdf.h:658-686`: `bsdf_blur` acts only on microfacet GGX/Beckmann
  (reflection, refraction, glass, thin-glass transmission), Ashikhmin-Shirley and hair.
  It also has the comment "TODO: Recompute energy preservation after blur?", so the
  multiscatter energy terms keep the original alpha that was set up.
- `kernel/closure/bsdf_microfacet.h:1095-1101`: `alpha_{x,y} = fmaxf(blur_roughness, alpha_{x,y})`.

Magnitude here: a diffuse-bounce pdf is at most about 1/pi, so blur_roughness (an
alpha) is at least `sqrt(1 - 0.32) * 0.5 = 0.41`. The gold sphere's alpha is 0.3^2 = 0.09.

## Fix options

1. **Implement Filter Glossy (Cycles parity).** This is pkg201 item C, parked on
   2026-08-29 (`.astroray_plan/docs/pkg201-item-c-filter-glossy-research.md`). The
   integrators need a per-path `minRayPdf`: the CPU spectral loops
   (`raytracer.h` about 4112, 5089, 5601) and a GPU wavefront SoA field. The material
   needs a per-hit alpha floor, applied to D, G, sample and pdf but **not** to the
   energy-compensation terms (Cycles keeps the setup-time alpha). On the CPU this is
   `principled.cpp` (`ggxReflectRGB`/`Spectral`, `ggxReflectConsistent*`, the
   `multiGgxGlass*` alpha, VNDF sample, `pdfLobe`, plus the aniso alphas) and
   metal/dielectric/thin_glass/disney. On the GPU it is the matching `gpu_pr_*`,
   `gpu_metal_*` and closure-graph sites, and `stageShadeBucketed` is already at 254
   registers. This is package-sized. #1231 shows the cost is a mean shift of up to 15 %
   wherever a glossy surface is seen through a diffuse bounce, not one firefly-honour row.
2. **Gate policy.** Render the Cycles reference legs with `blur_glossy = 0`, as the
   owner-approved `emission_backface_scale` reference convention does (2026-10-31).
   That passes this witness now (table above), but it hides a default-on Cycles
   behaviour that users see.

Evidence-only control added: `render_leg.py --attrib-spec '[{"kind":"filter_glossy","value":0}]'`.
Frames: `%LOCALAPPDATA%\astroray-evidence\2026-11-02\i1231\legs\{base,fg0,mb1,mb64,metal_off,metal_grey}`.
