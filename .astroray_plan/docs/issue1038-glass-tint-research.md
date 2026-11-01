# #1038 - Glass BSDF Color tint (research notes)

## Cycles source (Apache-2.0, blender/blender main, fetched 2026-10-06)

`intern/cycles/kernel/svm/closure.h`, `CLOSURE_BSDF_MICROFACET_GGX_GLASS_ID` case:

    fresnel->f0 = F0_from_ior(ior); fresnel->f90 = white; fresnel->exponent = -ior;
    const Spectrum color = max(rgb_to_spectrum(stack_load(stack, bsdf_data.color)), black);
    fresnel->tint = {float(reflective_caustics) * color, float(refractive_caustics) * color};

`intern/cycles/kernel/closure/bsdf_microfacet.h` `bsdf_microfacet_fresnel`: result is
`fresnel->tint * F` (reflectance = color*F, transmittance = color*(1-F)); under total
internal reflection it returns `{tint.reflectance, 0}` (= color).

The same file's Principled transmission case builds
`generalized_schlick_setup(ior, refl, refr, specular_tint, sqrt(clamped_base_color), thinfilm)`:
reflection tinted by `specular_tint` (scaling f0), transmission by `sqrt(base_color)`.

So Glass: reflection tint = Color, transmission tint = Color (full, per interface).
Principled: reflection tint = specular_tint, transmission tint = sqrt(base_color).

**Correction (#1200, 2026-11-01, v5.2.0 sources):** Principled's specular_tint is NOT a
reflection post-multiply. `generalized_schlick_setup` (bsdf_microfacet.h:111-124) sets
`f0 = F0_from_ior(ior) * specular_tint`, `reflection_tint = 1`; `generalized_schlick_fresnel`
(:316-321) gives R = mix(f0, 1, s), s = saturate((F - F0)/(1 - F0)), T = (1 - R) * sqrt(base),
so a tinted Principled glass rim goes to white. The Glass BSDF (svm/closure.h:816-822) keeps
f0 = F0 untinted and post-multiplies Color on both lobes, film or not. The engine now has
both fills (principled.cpp glassF0Tint / glassReflTint / glassTint; `glass_bsdf` selects the
Glass one; GPU twin gpu_pr_glass*), and the addon sends `glass_bsdf = 1` with the encoding
below. Before #1200 the non-film lobe used the Glass fill for Principled too, and the
thin-film lobe used the Principled fill for Glass too.

## Why the architect hypothesis (reflection only) was incomplete

The Blender addon exports `BSDF_GLASS` as native `principled` (transmission 1, base_color =
Color). Astroray's Principled transmission lobe is Cycles-Principled-faithful: reflection x
specular_tint (post-multiply), transmission x sqrt(base_color). So a Glass sphere got
transmission sqrt(Color) per interface and reflection 1, vs Cycles Color / Color. At the
sphere centre (two transmissions) the ratio is Color^(1) / Color^(2) = 1/Color =
(1.11, 1.00, 1.05) - the measured (1.119, 0.9985, 1.057). Reflection tint alone moves the
centre by only ~F*(1-c) (<0.4 %).

## Fix

Addon-only encoding of a Glass BSDF into the existing native params:
`specular_tint = Color`, `base_color = Color^2` (so sqrt(base) = Color). No engine or GPU
change; Principled and dielectric/glass plugins untouched. Analytic check (white furnace,
smooth sphere, centre ray, per-interface R = cF, T = c(1-F)):
`L = cF + c^2 (1-F)^2 / (1 - cF)`, F = ((n-1)/(n+1))^2.
