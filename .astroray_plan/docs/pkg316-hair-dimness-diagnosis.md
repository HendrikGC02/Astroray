# pkg316 — hair g/b dimness vs Cycles: diagnosis (#1051)

2026-10-06, lane f3. CPU MinGW build of `batch-f3/pkg316`; Cycles = Blender 5.2 CPU.
Evidence: `C:\Users\hgcom\OneDrive\Astroray\astra_run\batch-f\f3\`.

## Owners (four defects, three stages)

| # | Stage | Code site | Defect | Reference |
|---|---|---|---|---|
| 1 | BSDF (convention) | `hair_bsdf.h` `makeAlphaTilt` | pbrt cuticle-tilt sign: R lobe shifted toward the tip | Cycles `bsdf_hair_chiang_setup`: `bsdf->alpha = -bsdf->alpha` (Apache-2.0); Marschner 2003 (R toward the root) |
| 2 | Geometry | `curves.h`, `gpu_curve_intersect.cuh` leaf `v` | `v` grew on the wrong side of the axis: mirrored hair `h` and mirrored thick-curve normal | Cycles `h = dot(cross(Ng, X), Z)`; a Lambertian thick curve lit from +y was lit on −y |
| 3 | Parametrization (spectral) | `principled_hair.cpp` / `gpu_hair.cuh` `sigmaAAtLambda` | Direct Coloring σa(λ) was a piecewise-linear upsample of the RGB σa | pbrt-v4 `HairMaterial::GetBxDF` (materials.h): Albedo texture (Jakob–Hanika) → `SigmaAFromReflectance(c(λ))`, Apache-2.0 |
| 4 | Geometry | `curves.h` / `gpu_curve_intersect.cuh` hit depth | Thick curves shaded on the axis (pbrt flattened-test depth), up to one radius behind the lit surface | Cycles thick curves: `sd->P` on the swept surface; ribbons on the ray-facing plane through the axis |

#2 is energy-neutral (`h`-average symmetric) but mirrors every strand's glint and every
Lambertian curve's shading. #4 now applies only in THICK mode (`set_curve_thick_mode`,
Cycles Curves > Shape); RIBBONS keep the axis depth, so the corpus (authored RIBBONS)
keeps its shading point.

## Bisection table

| Check | Before | After | Note |
|---|---|---|---|
| 1. Lobe grid vs pbrt-v4 `HairBxDF` (pbrt tilt sign) | 6.3e-5 rel | — | BSDF math is a faithful pbrt port |
| 1. Lobe grid vs pbrt-v4 with the Cycles tilt sign | 77 (rel) | 6.9e-5 | test gate 1e-3 |
| 1. Furnace σa = 0, per lobe (reference) / engine total | 0.997–1.000 / 0.998–1.000 | same | R lobe 0.987 at h = 0.9, θo = 0: shared 10-term I0 series (pbrt-v4 and Cycles); 40 terms → 1.000 |
| 1. Engine R lobe alone (σa → ∞) / Fresnel | 0.996–1.000 | 0.997–1.000 | |
| 2. Melanin → σa, colour → σa vs Cycles `closure.h` | identical formulas | — | coefficients, −log remap, β_N polynomial |
| 2. Single fibre spectral colour / RGB reference (0.15, 0.09, 0.05) | r 1.038, g 0.994, b 0.994 | 1.006 / 1.000 / 1.005 | offline model of both upsamplings reproduced the engine to 1e-3 |
| 3. Single sunlit fibre, h-average / Cycles 5.2 (THICK) | 1.24 / 1.26 / 1.33 | 1.007 / 1.000 / 1.005 | per-row profile matches Cycles after #2 |
| 3. Thick Lambertian curve lit side | −y lit (mirrored) | +y lit | |
| 4. MIS vs BSDF-only, melanin tuft (CPU) | BSDF-only 1.012× MIS (4σ) | — | pdf ≠ sampling density through the truncated I0 (shared with Cycles); not a Cycles divergence |
| 3. Melanin tuft, sun, direct only / Cycles | — | 0.81 → 0.985 | owner #4: strand 5+6 pair keeps 0.55 (axis) vs 0.947 (surface), Cycles 0.959 |
| Melanin tuft (pkg225 scene), whole-frame energy / Cycles, R/B | 0.786, R/B 1.227 (Cycles 1.131) | 1.002, R/B 1.160 | gate seed; 4-seed mean 0.997, R/B 1.151 |
| Corpus v2 hair_tuft CPU, 3-seed mean (r, g, b, L) | 0.997 / 0.939 / 0.935 / 0.954 | 0.980 / 0.973 / 0.972 / 0.975 (5 seeds) | seed 278 0.989 / 0.981 / 0.981 / 0.983 |
| Corpus v2 @ortho hair_tuft CPU | 0.980 / 0.913 / 0.907 / 0.931 | 0.971 / 0.963 / 0.962 / 0.965 (5 seeds) | seed 278 0.964 / 0.954 / 0.959 / 0.957 |
| Non-hair scene (spheres, glass, metal, sun), CPU | — | byte-identical | |

## Residual (corpus only, achromatic ~2.5 %)

Grey-hair variant of the corpus scene (256 spp, 2 seeds; scalp-only ROI matches to 0.5 %):
Cycles RIBBONS reads 1.3 % brighter than Cycles THICK; Astroray (THICK normal, axis depth,
the corpus' RIBBONS mapping) is 2.1 % under Cycles THICK. A per-strand self-skip (Cycles
`intersection_skip_self` compares the curve prim, i.e. the whole strand:
`kernel/device/cpu/bvh.h` `segment.prim`; Astroray skips only the segment, #1037) recovered
1.1 % of that in a diagnostic build; not shipped (GPU traversal change, contradicts the #1037
adjacency test) — follow-up. Bounce limits (8 vs 32) move it < 0.3 %.

## Method notes

- Single-fibre scene: straight 2-point strand along x, radius 0.1, sun from (0.3, 0.5, 0.8)
  strength 2, ortho camera 1 unit wide, black world. The band sum over a column divided by
  2r/pixel gives the h-average independent of pixel filters.
- Cycles legs: `hair_curves` objects, Principled Hair (Chiang) node, factory settings with all
  bounce limits set, filter glossy 0, adaptive/denoise off; corpus legs via
  `benchmarks/blender_parity/render_leg.py --load-blend`.
