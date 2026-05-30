# VNDF Microfacet Dielectric BSDF Research

## Problem
Rough transmissive Disney/dielectric glass (transmission=1, roughness≥0.05) loses energy in white-furnace tests. Measured on RTX (ior 1.5, depth 32), CPU values show non-monotonic, deterministic loss:
- R=0.0→0.97 (smooth: correct ✔)
- R=0.05→0.81, 0.1→0.88, 0.3→0.355, 0.6→0.351, 1.0→0.562

Root cause: the current implementation uses full-NDF sampling (not VNDF) and mixes lobe-selection probabilities inconsistently between reflection/transmission paths.

## Solution
Replace rough microfacet dielectric transmission with Heitz 2018 VNDF-based sampling, mirroring PBRT-v4's `DielectricBxDF`.

## Primary References

### 1. PBRT-v4 DielectricBxDF (BSD-3-Clause)
- **Repository**: https://github.com/mmp/pbrt-v4
- **License**: BSD-3-Clause (compatible with our Apache-2.0)
- **Key files**:
  - `src/pbrt/bxdfs.h` — `DielectricBxDF` class declaration
  - `src/pbrt/bxdfs.cpp` — `DielectricBxDF::Sample_f`, `::f`, `::PDF` implementations
  - `src/pbrt/util/scattering.h` — `TrowbridgeReitzDistribution` (GGX NDF + VNDF sampling)
- **Core algorithm**:
  - `Sample_f`: samples microfacet normal via `mfDistrib.Sample_wm(wo, u)` (VNDF), then reflects or refracts off that microfacet. Fresnel at the microfacet determines the lobe.
  - **Transmission eval**: `D(wm) * (1 - F) * G(wo, wi) * |Dot(wi, wm) * Dot(wo, wm) / denom|` where `denom = Sqr(Dot(wi, wm) * etap + Dot(wo, wm)) * cosTheta_i * cosTheta_o`.
  - **Radiance transport correction**: `if (mode == TransportMode::Radiance) ft /= Sqr(etap)` applied to transmission term. Astroray IS a radiance path tracer, so this factor MUST be included.
  - **Transmission PDF**: `mfDistrib.PDF(wo, wm) * dwm_dwi * pt / (pr + pt)` where `dwm_dwi = AbsDot(wi, wm) / Sqr(Dot(wi, wm) + Dot(wo, wm) / etap)` is the half-vector Jacobian.

### 2. Heitz 2018 VNDF Sampling (JCGT, freely accessible)
- **Paper**: "Sampling the GGX Distribution of Visible Normals"
- **Citation**: Eric Heitz, JCGT Vol. 7, No. 4, 2018
- **URL**: https://jcgt.org/published/0007/04/01/
- **License**: Academic publication (algorithm is freely implementable)
- **Algorithm**: transforms viewing direction to hemispherical configuration, samples uniform disk, warps by visibility, reprojects to GGX ellipsoid. The VNDF PDF includes `G1(wo)` naturally; the sampling weight collapses to `G1(wi)`.

### 3. TrowbridgeReitzDistribution Methods (GGX)
From PBRT-v4 `src/pbrt/util/scattering.h`:
- **Lambda(w)**: `(sqrt(1 + alpha2 * tan2Theta) - 1) / 2` where `alpha2 = Sqr(CosPhi(w) * alpha_x) + Sqr(SinPhi(w) * alpha_y)` (anisotropic; isotropic uses `alpha_x = alpha_y = roughness^2`).
- **G1(w)**: `1 / (1 + Lambda(w))` ∈ [0,1], single-direction masking.
- **G(wo, wi)**: `1 / (1 + Lambda(wo) + Lambda(wi))`, joint masking-shadowing.
- **D(wm)**: `1 / (π * alpha_x * alpha_y * cos4Theta * Sqr(1 + e))` where `e` encodes anisotropic roughness (standard GGX NDF).

### 4. Cross-check: Cycles (Apache-2.0)
- **Repository**: https://github.com/blender/blender (Cycles is part of Blender)
- **License**: Apache-2.0
- **Key file**: `intern/cycles/kernel/closure/bsdf_microfacet.h`
- **Notes**: Cycles also uses VNDF sampling for rough dielectric (`bsdf_microfacet_ggx_sample`). Confirms the same algorithm structure.

## Critical eta² Warning
The radiance BTDF has TWO separate eta² factors:
1. **Non-symmetry radiance factor**: `1/(etap*etap)` on transmission (enter: 1/η², exit: η²). PBRT-v4 applies this as `if (mode == TransportMode::Radiance) ft /= Sqr(etap)`.
2. **Half-vector Jacobian**: `|HdotI * HdotT| / denom²` already contains eta dependencies.

DO NOT re-derive. Mirror PBRT-v4's transmission formula EXACTLY. The objective check: white-furnace clear glass at ALL roughness → ~1.0 (enter and exit eta² factors cancel).

## Implementation Plan
1. **Add VNDF sampler**: replace `sampleGgxMicroNormal` (current: full NDF sampling) with `sampleGgxVNDF(wo, u1, u2)` mirroring PBRT-v4's `TrowbridgeReitzDistribution::Sample_wm`. This requires transforming `wo` to local tangent space, sampling the VNDF, transforming back.
2. **Add VNDF PDF**: `pdfGgxVNDF(wo, wm)` includes `G1(wo)` naturally (= `D(wm) * G1(wo) * max(0, dot(wo, wm)) / abs(cosTheta(wo))`).
3. **Rewrite rough transmission sample**: sample `wm` via VNDF, compute Fresnel at `wm`, then:
   - If TIR or `u < F`: reflect off `wm`.
   - Else: refract off `wm` (transmission).
4. **Rewrite rough transmission eval**: use PBRT-v4's `DielectricBxDF::f` transmission formula with `mode == TransportMode::Radiance` eta² correction.
5. **Rewrite rough transmission PDF**: use PBRT-v4's `DielectricBxDF::PDF` transmission formula with half-vector Jacobian and Fresnel weighting.
6. **Keep CPU and GPU in lockstep**: identical math in `disney.cpp` and `gpu_materials.h`.

## Acceptance Criteria
1. `test_disney_rough_glass_furnace_energy_cpu` passes: clear Disney glass furnace ∈ [0.95,1.02] for R ∈ {0.1,0.3,0.6,1.0}.
2. GPU rough furnace also ∈ [0.92,1.05] for same R values.
3. Smooth glass (R=0) still ~0.97-0.99 (no regression).
4. `test_disney_rough_glass_furnace_deterministic` passes (32spp vs 256spp agree).
5. `test_dielectric_glass_furnace.py` still passes CPU+GPU.
6. No caustic gate test regressions.

## UPDATE 3 (2026-05-31): CPU residual root-caused — it is multi-scatter, not VNDF

A full instrumented pass (env `DISNEY_DBG=1`, see `scripts/diag_rough_glass_*.py`)
showed the remaining CPU residual is NOT a VNDF/low-alpha bug. The VNDF rewrite is
correct. The residual is **missing multiple-scattering energy compensation** for the
rough dielectric, masked by a **forced-TIR delta over-count**:
- At R=0.05, ~1.3M rough samples fall through to the delta path (grazing exit-TIR
  reflections whose VNDF `wi` lands below the surface — PBRT discards these). The
  delta-reflect branch then over-counts forced TIR at throughput ~21× (=1/Fresnel)
  instead of 1.0.
- The single-scattering Smith-G masking loss (transmission lobe has NO Kulla-Conty
  compensation, unlike the reflection lobe's `ggxCompensationFactor`) is only
  partly offset by that over-count. They balance at high R (~0.96) and diverge at
  low R (0.77).
- A faceforward of the VNDF sampling frame to `wo` was tried and is a **verified
  no-op** (`rec.normal` is already faceforwarded by the integrator) — do not repeat.

Fix = (A) correct the forced-TIR delta pdf to `transmission_` (not `F·transmission_`)
+ (B) Kulla-Conty 2017 multi-scatter compensation for the rough-dielectric lobe
(precompute `E_glass(alpha,mu,eta)`; apply `1+F_avg·(1-E)/E`). Full spec:
`packages/pkg118-rough-dielectric-multiscatter-energy.md`.

## Notes
- PBRT-v4's BSD-3-Clause license is compatible with Astroray's Apache-2.0.
- The VNDF algorithm is from a peer-reviewed academic paper (JCGT 2018), freely implementable.
- Cycles (Apache-2.0) independently confirms the same algorithm.
- All three sources (PBRT, Heitz, Cycles) agree on the VNDF approach for rough dielectrics.
