# pkg246 — RGB texture spectral round-trip contract

**Pillar:** 2 / 5
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at detailed architecture review
**Depends on:** existing spectral core; adjacent scopes remain separate.
Not dispatch eligible. Detailed architecture and independent review are required
before implementation. No priority promotion; Pillar 4 remains PAUSED.

Independent Terra SIGN-OFF to file, 2026-09-06, under the owner's authorization
to use Terra/DeepSeek while Claude is unavailable. Implementation gates remain UNRUN.

## Evidence and limited inference

During pkg230b, untouched addon `4035a00` with equivalent ordinary Mapping
reproduced the new affine path: mirror MAD/max = 0; arithmetic
MAD = 3.096041112371495e-8, max absolute difference = 0.00117380917.
Evidence: primary worktree `test_results/pkg230b/baseline-equivalence.json`
and `baseline-equivalence.log`; the log identifies the old addon/module path.
These tested RGB residuals predate the new affine routing.

The round's non-render quadrature using the existing LUT, CIE 1964 observer,
D65, and native XYZ/RGB matrix predicted mirror red ratio 1.126181 and
arithmetic 1.075620, versus rendered ratios about 1.130 / 1.079.
Example input `(.15,.45,.25)` reconstructed to `(.179286,.440182,.233979)`.
This correlation motivates a bounded contract audit; it is neither a complete
root-cause proof nor an independent physical oracle.

## Current path and scope

`include/advanced_features.h:315` caches per-texel `RGBAlbedoSpectrum`;
`:1625` consumes spectral texture reflectance. `src/spectrum.cpp:508`
clamps RGB and looks up the LUT (`:445`); `:300` integrates to XYZ.
`include/astroray/spectral.h:137` converts XYZ to linear RGB.
GPU consumers: `include/astroray/gpu_materials.h:102` and
`src/gpu/wavefront/stage_advance.cu:1425`.

Phase 0 pins source/data hashes, LUT fitting observer and illuminant, output
matrix, wavelength interval/normalization, and licenses before algorithm work.
Reuse `scripts/data/generate_spectrum_data.py` and its existing data/oracles.
Phase 1 defines the current fixed reconstruction contract and acceptable error
with neutral, primary, saturated, and RGB-grid cases; implement a reviewed
change only if evidence justifies it. Separate remaining scene effects.

## Acceptance — implementation/hardware/visual gates UNRUN

- [ ] Deterministic quadrature plus CPU/GPU and real Blender residuals establish
      the contract and predeclared tolerances; source/data/license audit retained.
- [ ] Any numerical change uses a cited algorithm; reflectance remains
      nonnegative and bounded, with linear energy floor AND ceiling gates.
- [ ] Preserve spectral transport, IR/band behavior, and dispersion; never force
      RGB identity by bypassing transport or violating physical reflectance.
- [ ] Save representative renders for Astra qualitative review; require native
      build, binding/caller, resource, and independent reviews as applicable.

## Boundaries and risks

[Pkg234](pkg234-image-texture-filtering.md) owns filtering/extension;
[pkg243](pkg243-raw-band-output-provenance.md) owns raw-band output/units.
[Pkg218](pkg218-spectral-colorimetry-fidelity.md) owns deferred lamp data and
selectable observer/camera features; this audit does not activate it or pkg133.
Fitting-basis mismatch, clipping, observer differences, and transport effects
must be distinguished. No implementation bundle with pkg247 or pkg248.
