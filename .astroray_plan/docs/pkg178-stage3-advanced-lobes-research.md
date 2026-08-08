# pkg178 Stage 3 — advanced-layer research + citations

**Date:** 2026-08-09. **Scope:** Coat, Sheen (LTC), Anisotropy, Emission+alpha,
Subsurface (approximate, D2=a) for the native Cycles Principled BSDF port. CPU +
GPU closure-graph twin. Every ported formula cites its Cycles source file/function
or paper per CLAUDE.md §6.

Reference pin: Blender Cycles @main (Blender 5.2-era), same pin as the Stage-0/1/2
research note `cycles-principled-port-research-2026-08.md`.

## Closure assembly + layering chain (Cycles `src/kernel/svm/closure.h`,
## `svm_node_closure_bsdf`, `CLOSURE_BSDF_PRINCIPLED_ID`)

Top-down weight flow (verbatim structure), fetched from Cycles main:

1. Alpha/transparent: `if (alpha < 1) { bsdf_transparent_setup(weight*(1-alpha)); weight *= alpha; }`
2. **Sheen** (above coat): closure weight = `sheen_weight * sheen_tint * weight`;
   then `weight = closure_layering_weight(sheen_albedo, weight)`.
3. **Coat**: clear GGX dielectric (coat_ior); `weight = closure_layering_weight(coat_albedo, weight)`;
   Beer absorption of the layers below:
   `cosNT = sqrt(1 - (1/coat_ior)^2 (1-cosNI^2)); optical_depth = 1/cosNT;`
   `weight *= mix(1, coat_tint^optical_depth, coat_weight)`. Coat normal from
   `coat_normal_offset` (defaults to shading N).
4. Emission (attenuated by coat/sheen above it).
5. **Metallic**: GGX + F82-tint; `weight *= (1-metallic)`.
6. **Transmission**: glass; `weight *= (1-transmission_weight)`.
7. **Specular** dielectric (generalized-Schlick).
8. **Subsurface**: `Bssrdf` random-walk (thick); `diffuse_weight = base_color*(1-subsurface_weight)*weight`.
9. **Diffuse**: `bsdf_diffuse_setup` or `bsdf_oren_nayar_setup` when diffuse_roughness>0.

## Coat (Cycles svm/closure.h coat layer + `bsdf_microfacet.h`)

Clear dielectric GGX reflection reusing the Stage-1 specular machinery with
coat_ior/coat_roughness and F0 = `F0_from_ior(coat_ior)`, generalized-Schlick
Fresnel. Beer absorption applied to the running weight exactly as above. Energy
compensation + directional-albedo layering reuse the shipped
`energy_compensation.h` / `gpu_ggx_tables` (NOT forked).

## Sheen — LTC microfiber (Cycles `src/kernel/closure/bsdf_sheen.h`, Apache-2.0)

Model: Zeltner, Burley, Chiang, *Practical Multiple-Scattering Sheen Using
Linearly Transformed Cosines*, SIGGRAPH 2022 Talk. Reference implementation:
github.com/tizian/ltc-sheen (Apache-2.0).

- Setup: view-dependent frame `make_orthonormals_safe_tangent(N, wi)`; fetch
  `(transformA=aInv, transformB=bInv, albedo)` by bilinear interp of a 32x32 LTC
  table (`lookup_table_read_2D(cosNI, roughness, 32, 32)`). Skip closure if
  `|aInv|<1e-5 || albedo<1e-5`. closure weight `*= albedo`.
- Eval / pdf (`bsdf_sheen_eval`): `localO = to_local(wo)`;
  `lenSqr = (a*localO.x + b*localO.z)^2 + (a*localO.y)^2 + localO.z^2`;
  `val = 1/pi * max(localO.z,0) * (a/lenSqr)^2`; `pdf = val`. (Cycles bsdf eval
  returns BSDF*cos, matching Astroray's per-lobe convention — pbrt-v3 tizian eval
  divides by cosThetaI, then the integrator re-multiplies, giving the same `val`.)
- Sample (`bsdf_sheen_sample`): `disk = sample_uniform_disk(rand);
  diskZ = sqrt(1-|disk|^2); localO = normalize((disk.x - diskZ*b, disk.y, diskZ*a));
  wo = to_global(localO)`.

### Table provenance (NOT hand-transcribed — CLAUDE.md §6)

`include/astroray/sheen_ltc_table.h` is generated mechanically from
`fitting/python/data/ltc_table_sheen_approx.cpp` in tizian/ltc-sheen (Apache-2.0),
a `Vector3f[32][32]` of `{aInv, bInv, albedo}` laid out `[roughness][cosTheta]` —
the SAME data Cycles uploads as `kernel_data.tables.sheen_ltc` (the "approx"
2-parameter LTC, matching Cycles' transformA/transformB). Verified 1024 triples
(32x32) parsed. The header is host/device (`__device__` under `__CUDACC__`).

## Anisotropy — NOT implemented this pass (SURFACED FORK, see report)

Cycles anisotropy (`svm/closure.h`): `aspect = sqrt(1 - anisotropic*0.9);
alpha_x = roughness^2/aspect; alpha_y = roughness^2*aspect;` tangent from
`tangent_offset` rotated by `anisotropic_rotation * 2pi` about N; applied to
metallic + specular via anisotropic GGX (Trowbridge-Reitz aniso D, anisotropic
Smith masking, anisotropic VNDF sampling). Faithful anisotropy requires replacing
the merged/validated **isotropic** Schlick-GGX masking (`smithG_k`, used by the
Stage-1/2 specular + metallic lobes and byte-matched CPU/GPU) with true
anisotropic Smith Lambda. That re-opens the Stage-1/2 furnace + chi2 + CPU/GPU
byte-twin acceptance for the isotropic case. This is a genuine fork the spec does
not pre-decide; deferred to the lead/owner (see report).

## Emission + alpha

- **Emission (CPU, done):** `emitted()/emittedSpectral()/getEmission()/isEmissive()`
  return `emission_color * emission_strength` (two-sided, EmissivePlugin lineage;
  `RGBIlluminantSpectrum` for spectral). Default emission_color (0,0,0) -> 0
  (non-regressing). Verified: emissive Principled self-illuminates on a black bg;
  non-emissive stays dark.
- **Alpha (SURFACED):** Cycles adds a Transparent closure `weight*(1-alpha)` and
  scales the surface by alpha. In Astroray this is entangled with the one-sample-MIS
  lobe-selection normalization (the shared delta-glass `f/pdf = weight/qj` path,
  where correctness relies on W≈1). Adding a transparent delta lobe changes W and
  risks the already-validated delta-glass energy. Deferred to the lead (see report).
- **GPU emission (SURFACED):** `scene_upload.cu` only extracts emission /
  GAreaLight for `gpuType=="diffuse_light"`; an emissive Principled on the
  wavefront leg needs that extraction to learn the closure-graph emission path.

## Subsurface — APPROXIMATE (owner decision D2 = option (a))

Reuses the diffusion-style plugin lineage (`subsurface.cpp`): a Lambertian
base-colour lobe with `weight = base_color * subsurface_weight * weight`, and the
diffuse lobe scaled by `(1 - subsurface_weight)` (Cycles' `diffuse_weight`
split). Captures SSS energy/colour but NOT the sub-surface blur -> wider declared
parity band vs Cycles' random-walk. SEAM: converge to the transport-correct
random walk in `include/astroray/bssrdf_random_walk.h` (PR #565) when D2
converges; that needs an "intersect within this object only" integrator query, so
it is NOT a `Material::eval` closure and cannot be wired here.

## Sources

- Cycles @main: `src/kernel/svm/closure.h`, `src/kernel/closure/bsdf_sheen.h`,
  `bsdf_microfacet.h`, `bsdf_util.h`, `bsdf_oren_nayar.h` (Apache-2.0 / BSD-3-Clause).
- Zeltner, Burley, Chiang 2022, *Practical Multiple-Scattering Sheen Using LTC*
  (SIGGRAPH Talk); reference + table: https://github.com/tizian/ltc-sheen (Apache-2.0).
- Heitz et al. 2016 (LTC), Heitz 2018 (VNDF), Kulla & Conty 2017 (multiscatter),
  Walter 2007 (microfacet refraction), Kutz/Hoffman F82-tint, Fujii/OpenPBR (EON).
