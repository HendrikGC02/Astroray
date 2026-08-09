# Anisotropic Principled GGX — research notes (pkg178 Stage-3b PR-4b)

Source of truth: Blender Cycles `intern/cycles/kernel/closure/bsdf_microfacet.h`
and `intern/cycles/kernel/svm/closure.h` (Blender main, Apache-2.0 / BSD-3-Clause).
Fetched 2026-08-09. License compatible with Astroray (same lineage as PR-4a /
disney.cpp / energy_compensation.h).

## Parameter mapping (svm/closure.h, CLOSURE_BSDF_PRINCIPLED_ID)

```c
float alpha_x = sqr(roughness);   // roughness = the roughness socket value
float alpha_y = sqr(roughness);
if (anisotropic > 0 && tangent valid) {
  const float aspect = sqrtf(1.0f - anisotropic * 0.9f);
  alpha_x /= aspect;
  alpha_y *= aspect;
}
const float anisotropic_rotation = stack_load(...);
if (anisotropic_rotation != 0.0f)
  T = rotate_around_axis(T, N, anisotropic_rotation * M_2PI_F);
// bsdf->T = T; bsdf->alpha_x = alpha_x; bsdf->alpha_y = alpha_y;
```
`sqr(roughness)` is Cycles `alpha_x`; Astroray's iso code calls this scalar `a`
(= `max(roughness*roughness, 0.0064)`). Astroray's `D_GTR2(NdotH, a)` squares `a`
internally, so Astroray `a` == Cycles `alpha_x`, and `a*a` == Cycles `alpha2`.
Applies to the METALLIC and SPECULAR lobes only; coat/sheen/diffuse stay iso;
transmission stays iso with `alpha2 = alpha_x*alpha_y` (so `alpha = roughness^2`,
unchanged → transmission is byte-identical regardless of anisotropic).

## Microfacet functions (bsdf_microfacet.h)

```c
bsdf_lambda_from_sqr_alpha_tan_n(t) = 0.5f * (sqrtf(1 + t) - 1)               // GGX
bsdf_aniso_lambda(ax, ay, V) = lambda_from(( (ax*V.x)^2 + (ay*V.y)^2 ) / V.z^2)
bsdf_aniso_D(ax, ay, H):  H /= (ax, ay, 1);  alpha2 = ax*ay;
                          return M_1_PI / (alpha2 * len_squared(H)^2)
bsdf_G(alpha2, cNI, cNO) = 1 / (1 + lambda(alpha2,cNI) + lambda(alpha2,cNO))   // height-correlated
```
`bsdf_microfacet_eval` branch:
```c
if (alpha_x == alpha_y || is_transmission) { /* iso: alpha2 = ax*ay */ }
else { make_orthonormals_tangent(N, T, &X, &Y);  local_H/I/O; aniso D/lambda }
```
Astroray mirrors this branch: `anisotropic <= 0` → the EXACT PR-4a iso code
(bit-identical); else the aniso local-frame code. Iso reduction is exact by
construction (the iso branch is literally unchanged).

## Sampling — NDF (not VNDF)

Astroray's reflect lobes (specular/metallic/coat) importance-sample the **NDF**
(half-vector ∝ D(h)·cosθ_h), NOT Cycles' VNDF — a pre-existing, internally
consistent divergence (the pdf matches the sampler, so it is unbiased; only the
transmission lobe uses VNDF). Per the Stage-3 design decision §3 ("NDF-sampled
lobes: aniso D changes sampling and pdf together") the aniso generalization keeps
NDF sampling. Anisotropic NDF half-vector via slope stretch (Heitz 2018 slope
domain; Walter 2007 App. B): isotropic-space slope `(r cosφ, r sinφ)` with
`r = sqrt(u2/(1-u2))`, `φ = 2π u1`, stretched by `(alpha_x, alpha_y)`:
```
h_local = normalize(-alpha_x*r*cosφ, -alpha_y*r*sinφ, 1)
```
Same 2 uniforms as the iso path → RNG stream count preserved. pdf(wi) =
D_aniso(h)·|N·h| / (4·|wo·h|), the direct aniso generalization of the iso
`D_GTR2(NdotH,a)·NdotH/(4·HdotV)`. At alpha_x==alpha_y this distribution is
identical to the iso sampler (verified: tan²θ = a²·u2/(1-u2), φ = 2π u1 both), so
the iso-continuity gate (anisotropic=1e-4 vs 0) holds within MC noise.

## Energy compensation

Cycles `microfacet_ggx_preserve_energy`: feeds the ISO E-table with
`rough = sqrtf(sqrtf(alpha_x * alpha_y))`. At iso this equals `roughness`, so the
iso branch passes `roughness` verbatim (bit-identical); the aniso branch passes
`sqrt(sqrt(ax*ay))`. Tables (`ggxE`/`ggxEavg`/`ggxDarkeningChannel`) reused as-is.

## Tangent frame

CPU uses `rec.uvTangent` (PR-3, active-UV Lengyel tangent) rotated by
`anisotropic_rotation*2π` (Rodrigues; T⊥N ⇒ `T cosθ + (N×T) sinθ`), then
`make_orthonormals_tangent`: `Y = normalize(N×T)`, `X = Y×N`. GPU mirrors this;
the device UV-aligned tangent is computed in the shade path from the per-triangle
UVs uploaded to `GTriangle` (only for anisotropic-principled triangles).
