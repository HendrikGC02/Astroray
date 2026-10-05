# Microfacet transmission at eta ~ 1: Cycles treats it as singular (#1084 M2)

Source: Blender Cycles `src/kernel/closure/bsdf_microfacet.h`, `bsdf_microfacet_sample()`
(SPDX BSD-3-Clause, adapted from Open Shading Language; compatible).

```c
bool m_singular = roughness_is_almost_specular(alpha_x, alpha_y);
...
if (do_refract) {
  ...
  /* If the IOR is close enough to 1.0, just treat the interaction as specular. */
  m_singular = m_singular || (fabsf(m_eta - 1.0f) < 1e-4f);
```

Why: at eta == 1 the refraction half-vector `wi*eta + wo` is the zero vector for the
straight-through direction wi = -wo, so the rough lobe's eval/pdf collapse to 0 (the #1084
black pane). Cycles' answer is not a nudged eta but a delta (pure pass-through) lobe.

Astroray: `LobeKind::Transmission` rough lobe sets `isDelta = roughness <= kDelta ||
|ior-1| < 1e-4` with `ior` unchanged (CPU `plugins/materials/principled.cpp`, GPU twin
`gpu_pr_assembleLobes` in `include/astroray/gpu_materials.h`). The delta transmission path
then refracts with eta ~ 1 (wi = -wo to ~1e-5) and the Fresnel factor is ~0, so every
sample transmits.

The earlier 1.0001 nudge rendered within 0.5% of this, but kept a finite-pdf peaked lobe
(measured pdf ~1e7, sampled |wi+wo| up to 2e-3) that is not what Cycles does.
