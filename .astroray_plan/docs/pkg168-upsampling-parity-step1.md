# pkg168 Step 1 — CPU↔GPU RGB→spectral upsampling parity: A/B verdict

**Date:** 2026-08-02 (RTX 5070 Ti)
**Branch:** pkg168-rgb-spectral-upsampling-parity (PR #539)
**Founding evidence:** pkg156 residual decomposition post-#537 — depth-4 wavefront
naive-mode GPU/CPU ratio **[1.014, 1.007, 1.014]**, SSIM 0.9955 vs the
aspirational 0.998, channel-asymmetric, bounce-2 onset.

## Verdict: TABLES CLEAN → the gap is in the CALL STRUCTURE (fork B)

The CPU (`RGBAlbedoSpectrum`/`RGBIlluminantSpectrum::evalAt`, src/spectrum.cpp)
and GPU (`gpu_rgbSpectrumAt` → `gpu_jhEvalSpectrum`, the exact scalar
`gpu_rgbToSampledSpectrum` writes per sample) upsamplers agree at unit level to
float precision. The render-level [1.014, 1.007, 1.014] signature is **not born
in the upsampling tables** and cannot be fixed there. Per the spec fork this
routes to the call structure (pkg163 class rule: legs that upsample at different
points/frequencies along a path do not commute).

## Method — unit-level A/B (no renders)

Two test-only debug probes feed identical `(rgb, λ)` grids to each leg:

- **CPU:** `astroray._cpu_rgb_upsample_batch(rgbs, lambdas, mode)` — module free
  function (module/blender_module.cpp), calls `RGB*Spectrum::evalAt` directly.
- **GPU:** `Renderer._gpu_rgb_upsample_batch(rgbs, lambdas, mode)` →
  `CUDARenderer::rgbUpsampleBatch` → `launchRgbUpsampleBatch`
  (src/gpu/gpu_spectral_tables.cu), a batched 1-thread-per-`(rgb,λ)` kernel over
  `gpu_rgbSpectrumAt`. Mirrors the pkg54d `launchProfileLookup` probe pattern.

Grid: the pkg156 naive-scene albedos (veg [0.20,0.55,0.30], water
[0.05,0.10,0.18], metal [0.85,0.85,0.88]) + sRGB primaries + a neutral-grey ramp
+ the scene light [1,1,1] and background tint [0.05,0.05,0.07], over 380–780 nm
at 5 nm (81 samples). Gate: `tests/test_pkg168_upsampling_parity.py`.

## Results (band-integrated mean ratio GPU/CPU — the render-relevant quantity)

**ALBEDO** (overall meanRel = 2.06e-6):

| point  | maxRel(1λ) | meanRel  | meanRatio |
|--------|-----------|----------|-----------|
| veg    | 7.95e-6   | 3.82e-6  | 1.000004  |
| water  | 1.95e-6   | 3.50e-7  | 1.000000  |
| metal  | 2.10e-7   | 7.53e-8  | 1.000000  |
| red    | 2.90e-6   | 3.29e-7  | 1.000000  |
| green  | 2.01e-4   | 1.74e-5  | 1.000000  |
| blue   | 2.03e-6   | 4.04e-7  | 1.000000  |
| grey05 | 5.27e-7   | 1.85e-7  | 1.000000  |
| grey18 | 1.66e-7   | 4.31e-8  | 1.000000  |
| grey50 | 0.0       | 0.0      | 1.000000  |
| grey85 | 2.80e-7   | 6.23e-8  | 1.000000  |
| white  | 5.96e-8   | 1.77e-8  | 1.000000  |

**ILLUMINANT** (overall meanRel = 1.24e-7): light 1.000000, bg_tint 1.000000,
grey18 1.000000, grey50 1.000000.

The only non-negligible per-λ blip is the fully-saturated `green` primary
([0,1,0]) at one edge wavelength (maxRel 2e-4) — fma ordering on a near-zero
sigmoid value at a LUT edge; its band-integrated ratio is 1.000000, i.e. it
contributes nothing to any channel. No point shows anything approaching the
render-level 0.7–1.4 % channel offset.

## Mechanism enumeration — every table-side candidate ruled out

The two legs are byte-mirror implementations, which the numbers confirm:

- **Sigmoid evaluator:** shared single source of truth
  `jhEvalSpectrumF` (include/astroray/gpu_materials.h), `__host__ __device__`,
  `std::fma`/`fmaf` fused on both — bit-identical modulo fma ordering.
- **LUT resolution / layout:** GPU uploads the identical 64³ `.coeff` verbatim
  (`uploadJakobHanikaLut`); same `[channel][z][y][x][coeff]` flat layout.
- **Interpolation order:** `gpu_jhLookupCoeffs` mirrors `JakobHanikaLut::lookup`
  exactly — same max-channel sub-table pick, same scale-table `k` scan, same
  trilinear (tx,ty,tz) blend, same [0,1] clamps.
- **Coefficient-fetch quantization / float precision:** meanRel 2e-6 (albedo),
  1e-7 (illuminant) — pure fp32 rounding, no systematic bias.
- **Illuminant normalization:** CPU factors `scale_ = 2·max(rgb)` in the ctor
  then `scale·sigmoid·D65`; GPU does the same inline in `gpu_rgbSpectrumAt`
  (GSPEC_RGB_ILLUMINANT). Ratios 1.000000 — equivalent.

## Where the gap actually is (Step 2, out of Step-1 scope)

Both legs nominally upsample **per bounce** with the path's fixed stratified
λ: CPU via `Material::sampleSpectral` → `bss.f_spectral`
(src/cpu/wavefront/reference_pt_production.cpp:219–223), GPU via
`gpu_rgbToSampledSpectrum(mat.baseColor, lambdas, …)` in the shade stage
(src/gpu/wavefront/stage_shade_lambertian.cu:188). So the divergence is subtler
than upsample-frequency — consistent with the **bounce-2 onset** (depth-1 ratio
~1.00). Candidate non-commuting mechanisms to localize, in priority order:

1. A spectral↔RGB (or spectral↔XYZ) intermediate collapse between bounces on one
   leg only — the classic pkg163 "sum-then-upsample vs upsample-then-sum" fork.
2. Throughput×`f_spectral` update ordering vs the clamp / Russian-roulette
   luminance metric (`toXYZ` vs mean-of-samples) differing per leg — note the
   CPU RR uses `throughput.toXYZ(lambdas).Y` and a `maxValue()>10` clamp
   (reference_pt_production.cpp:189–256); the wavefront's metric must be checked
   at the same capture moment.

**Recommended Step 2:** the pkg55 per-bounce snapshot harness, capture pinned
IMMEDIATELY after the throughput×albedo update at each bounce on both legs
(memory `wavefront-snapshot-semantics-class-of-bug`), focused on bounce 2. Re-scope
the fix to the convicted call site. This is larger than Step 1's scope, so per the
spec ("if Step 1 convicts but the fix is larger, STOP after the conviction") this
package stops here; Step 2 needs its own dispatch.

## Consequence for the headline DoD

pkg156's 0.998 SSIM restoration is **blocked on the Step-2 call-structure fix** —
it is NOT achievable in this Step-1 PR, because the tables (the only thing Step 1
could have convicted+fixed) are clean. pkg156's gate stays at 0.995 until Step 2
lands.

## pkg153 cross-link (bisect intel — NOT gate ownership)

pkg153 keeps ownership of its three quarantined env-scene ratios. This result is
an anchor for pkg153's bisect: the shared RGB→spectral **tables** are exonerated,
so pkg153's R-drift (and the emitter-linked ~4.6 pp discriminator it notes) must
come from the same call-structure arc or a separate light-energy co-mechanism —
not the upsampling LUT. No pkg153 gates touched here.
