# pkg246 — RGB texture spectral round-trip contract

**Pillar:** 2
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD
**Depends on:** TBD

---

## Goal

Before: RGB textures traverse the spectral pipeline through a fixed RGB→spectrum→RGB reconstruction path (per-texel `RGBAlbedoSpectrum` caching, RGB clamp plus LUT lookup, XYZ integration, XYZ→linear-RGB conversion, plus GPU consumers) whose contract and acceptable error are not yet defined. After: Phase 0 pins source/data hashes, LUT fitting observer and illuminant, output matrix, wavelength interval/normalization, and licenses before algorithm work, and Phase 1 defines the current fixed reconstruction contract and acceptable error with neutral, primary, saturated, and RGB-grid cases — implementing a reviewed change only if evidence justifies it and separating remaining scene effects.

---

## Context

This package serves Pillar 2 / 5. It depends on the existing spectral core; adjacent scopes remain separate. Not dispatch eligible: detailed architecture and independent review are required before implementation. No priority promotion; Pillar 4 remains PAUSED. Effort is to be determined at the detailed architecture review. Independent Terra SIGN-OFF to file, 2026-09-06, under the owner's authorization to use Terra/DeepSeek while Claude is unavailable. Implementation gates remain UNRUN.

---

## Evidence

- 2026-09-06: Independent Terra SIGN-OFF to file, under the owner's
  authorization to use Terra/DeepSeek while Claude is unavailable.
  Implementation gates remain UNRUN.
- During pkg230b, the untouched addon `4035a00` with equivalent ordinary
  Mapping reproduced the new affine path: mirror MAD/max = 0; arithmetic
  MAD = 3.096041112371495e-8, max absolute difference = 0.00117380917.
  Evidence: primary worktree `test_results/pkg230b/baseline-equivalence.json`
  and `baseline-equivalence.log`; the log identifies the old addon/module path.
  These tested RGB residuals predate the new affine routing.
- The round's non-render quadrature using the existing LUT, CIE 1964 observer,
  D65, and native XYZ/RGB matrix predicted mirror red ratio 1.126181 and
  arithmetic 1.075620, versus rendered ratios about 1.130 / 1.079.
  Example input `(.15,.45,.25)` reconstructed to `(.179286,.440182,.233979)`.
  This correlation motivates a bounded contract audit; it is neither a
  complete root-cause proof nor an independent physical oracle.
- Current round-trip path: `include/advanced_features.h:315` caches per-texel
  `RGBAlbedoSpectrum`; `:1625` consumes spectral texture reflectance.
  `src/spectrum.cpp:508` clamps RGB and looks up the LUT (`:445`); `:300`
  integrates to XYZ. `include/astroray/spectral.h:137` converts XYZ to linear
  RGB. GPU consumers: `include/astroray/gpu_materials.h:102` and
  `src/gpu/wavefront/stage_advance.cu:1425`.

---

## Reference

- Reuse: `scripts/data/generate_spectrum_data.py` and its existing data/oracles.
- Baseline-equivalence artifacts (primary worktree): `test_results/pkg230b/baseline-equivalence.json` and `test_results/pkg230b/baseline-equivalence.log`.

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `include/advanced_features.h` | Round-trip path under audit: caches per-texel `RGBAlbedoSpectrum` (:315) and consumes spectral texture reflectance (:1625); a reviewed change is implemented only if Phase 1 evidence justifies it. |
| `src/spectrum.cpp` | Round-trip path under audit: clamps RGB and looks up the LUT (:508; LUT at :445) and integrates to XYZ (:300); a reviewed change is implemented only if Phase 1 evidence justifies it. |
| `include/astroray/spectral.h` | Round-trip path under audit: converts XYZ to linear RGB (:137); a reviewed change is implemented only if Phase 1 evidence justifies it. |
| `include/astroray/gpu_materials.h` | GPU consumer under audit (:102); a reviewed change is implemented only if Phase 1 evidence justifies it. |
| `src/gpu/wavefront/stage_advance.cu` | GPU consumer under audit (:1425); a reviewed change is implemented only if Phase 1 evidence justifies it. |

### Key design decisions

#### Phase 0

Phase 0 pins source/data hashes, LUT fitting observer and illuminant, output
matrix, wavelength interval/normalization, and licenses before algorithm work.
Reuse `scripts/data/generate_spectrum_data.py` and its existing data/oracles.

#### Phase 1

Phase 1 defines the current fixed reconstruction contract and acceptable error
with neutral, primary, saturated, and RGB-grid cases; implement a reviewed
change only if evidence justifies it. Separate remaining scene effects.

---

## Acceptance criteria

Implementation, hardware, and visual gates are UNRUN.

- [ ] Deterministic quadrature plus CPU/GPU and real Blender residuals
      establish the contract and predeclared tolerances; source/data/license
      audit retained.
- [ ] Any numerical change uses a cited algorithm; reflectance remains
      nonnegative and bounded, with linear energy floor AND ceiling gates.
- [ ] Preserve spectral transport, IR/band behavior, and dispersion; never
      force RGB identity by bypassing transport or violating physical
      reflectance.
- [ ] Save representative renders for Astra qualitative review; require native
      build, binding/caller, resource, and independent reviews as applicable.

---

## Non-goals

- [Pkg234](pkg234-image-texture-filtering.md) owns filtering/extension.
- [pkg243](pkg243-raw-band-output-provenance.md) owns raw-band output/units.
- [Pkg218](pkg218-spectral-colorimetry-fidelity.md) owns deferred lamp data and
  selectable observer/camera features; this audit does not activate it or
  pkg133.
- Risk: fitting-basis mismatch, clipping, observer differences, and transport
  effects must be distinguished.
- No implementation bundle with pkg247 or pkg248.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)
