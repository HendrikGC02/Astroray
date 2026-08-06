# pkg168 Step 2 — call-structure localization + diffuse upsampling fix

**Date:** 2026-08-02 (RTX 5070 Ti)
**Branch:** pkg168-step2-callstructure (PR #541)
**Builds on:** Step 1 (PR #539, merged 1cb6485) — tables proven bit-clean, fork
routed to CALL STRUCTURE.

## Verdict

Step 1 exonerated the JH upsampling TABLES. Step 2 found — and fixed — a genuine
call-structure divergence in the GPU diffuse shading, and separately localized
the pkg156 gate's *dominant* residual to an unrelated triangle-geometry
transport bias that is outside pkg168's RGB→spectral-upsampling charter.

## Bug 1 (FIXED here): diffuse upsamples the pre-scaled BSDF value

`gpu_material_sample_spectral` (include/astroray/gpu_materials.h) shaded a
diffuse lobe (native `GMAT_LAMBERTIAN` or a diffuse-only closure graph — plain
"lambertian" lowers to a closure graph via `Lambertian::closureGraph()`) by
upsampling the pre-scaled RGB BSDF value `s.f = albedo·cosθ/π`:

    s.fSpectral = gpu_rgbToSampledSpectrum(s.f, wl, mode);   // WRONG

The CPU oracle (`Lambertian::evalSpectral`, raytracer.h) upsamples the pure
albedo COLOUR and applies `cosθ/π` as a wavelength-flat scalar:

    albedoSpec.sample(lambdas) * (cosθ/π)                    // oracle

Jakob-Hanika upsampling is **nonlinear in magnitude**: `upsample(k·c) ≠
k·upsample(c)`. Scaling an RGB by a scalar preserves its chromaticity (x,y in the
LUT) but moves its z (max-channel) coordinate, selecting different sigmoid
coefficients → a different spectrum SHAPE. Both shapes integrate to the same XYZ,
so a *direct* view is unaffected (Step-1 unit probe and a background-only render
are clean), but the shape mismatch bites the moment the throughput spectrum is
MULTIPLIED by the next factor (next-bounce albedo / illuminant) and integrated —
a chroma-dependent, per-bounce-compounding divergence. This is the exact pkg163
class rule ("upsample points don't commute") Step 1 predicted, and the direct
analog of the pkg163 metal fix (already at gpu_materials.h:~1560).

**Empirical proof** (single diffuse sphere, white illuminant, GPU/CPU per-channel
mean ratio, spp 8192, two seeds — stable):

| albedo            | pre-fix                    | post-fix                   |
|-------------------|----------------------------|----------------------------|
| grey [.5,.5,.5]   | [0.9988,0.9989,0.9989]     | [0.9998,1.0001,1.0002]     |
| red  [.9,.1,.1]   | [0.9751,1.0045,0.9934]     | [0.9999,1.0001,1.0002]     |
| blue [.1,.1,.9]   | [1.0195,0.9857,1.0188]     | [0.9999,1.0000,1.0002]     |

Neutral albedo was already ~clean (uniform, no channel asymmetry) — the bug is
chroma-driven, exactly as the nonlinearity predicts. Saturated diffuse colour was
up to **2.5% per channel** off; post-fix all within ~0.02%.

**Fix:** `gpu_lambertian_eval_spectral` upsamples the reflectance colour
per-lambda and applies the (wavelength-flat) geometric/HK scalar recovered from
`gpu_lambertian_eval`. Routed from `gpu_material_sample_spectral`,
`gpu_material_eval_spectral`, and `gpu_closure_graph_eval_spectral` for diffuse /
diffuse-only-closure-graph lobes. Glass/Disney/dielectric/metal lobes are
untouched (the eta²>1 magnitude-factoring of pkg118/pkg152 and the pkg163 metal
path are gated out). Regression: `tests/test_pkg168_diffuse_upsample_parity.py`.

## Bug 2 (localized, OUT OF SCOPE, NOT fixed): triangle-geometry transport bias

The pkg156 gate scene (`scenes/multiwavelength_parity.py`) is a dim Cornell-like
room — floor + back wall + one sphere, all Lambertian, lit only by the dim
background in naive mode (the ceiling light is invisible: naive mode takes
emission only on `bounce==0||wasSpecular`, and every bounce here is diffuse). The
whole image is dim (max channel ~0.03). After Bug 1's fix the gate is
**unchanged** at SSIM 0.9955 / ratio ~[1.016,1.010,1.014].

Isolation shows why: the SAME diffuse material is **clean on a sphere** but
diverges on **triangles**:

| geometry (veg albedo, white bg, depth 4) | GPU/CPU ratio            |
|------------------------------------------|--------------------------|
| sphere                                   | [0.99988,1.00004,1.00004]|
| floor (triangles)                        | [1.01043,1.00583,1.01015]|

A **neutral** floor also diverges — uniformly [1.0061,1.0063,1.0066] (no channel
asymmetry) — so this is a **scalar geometry/transport bias, not RGB→spectral
upsampling**. It is single-bounce (constant across depths 2–4) and independent of
background brightness/colour (the pkg156 ratio is identical for bg [0.05,0.05,
0.07], [0.5,0.5,0.5], and [1,1,1]). Candidate causes (for a follow-up spec):
triangle shading-vs-geometric normal, cosθ / normal normalization, or the
`f/(pdf+1e-3)` epsilon interacting with the triangle cosθ distribution — a
transport-parity issue in the sibling class to pkg153, NOT this package's
RGB→spectral-upsampling charter.

## Disposition

- **Bug 1 fixed** — pkg168's charter (RGB→spectral upsampling parity) is now
  correct for diffuse lobes; verified on saturated diffuse renders + full
  material regression suite (metal/disney/glass/closure-graph/wavefront_diff/
  multiwavelength all green, no regression).
- **pkg156's 0.998 restoration is NOT achieved and the gate is NOT re-pinned.**
  The dominant residual is Bug 2 (triangle transport), outside this package's
  scope. Per the spec ("localize but if the fix exceeds scope, STOP at
  conviction"), Step 2 stops here and files Bug 2 as a follow-up. pkg156 stays at
  0.995.
- **pkg153 cross-link:** Bug 2 is a transport-parity bias in the same family;
  Bug 1's fix does not move pkg153's quarantined env-scene ratios (they are
  triangle/env scenes dominated by Bug 2). No pkg153 gates touched.
