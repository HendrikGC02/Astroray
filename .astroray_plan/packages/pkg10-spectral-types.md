# pkg10 — Spectral types

**Pillar:** 2
**Track:** A
**Status:** done
**Estimated effort:** 1 session (~3–4 h)
**Depends on:** pkg06 (Pillar 1 complete)

---

## Goal

**Before:** the only spectral support is the GR renderer's
`include/astroray/spectral.h` (4-wavelength double-precision
`SpectralSample`, CIE 1931 2° observer, 380–780 nm). There is no
RGB→spectrum upsampling; `Integrator::sampleSpectral` defaults to a
flat-luminance fallback.

**After:** `include/astroray/spectrum.h` defines `SampledWavelengths`,
`SampledSpectrum`, and `RGBAlbedoSpectrum` / `RGBUnboundedSpectrum` /
`RGBIlluminantSpectrum` (float, 4 samples, 360–830 nm) following the
PBRT v4 design. A Jakob-Hanika LUT loader reads
`data/spectra/rgb_to_spectrum_srgb.coeff` at first use. CIE 1964 10°
CMF and D65 SPD are embedded as generated `.inc` headers. Python
bindings expose the full type surface so pytest can cover each type
directly. Unit tests validate arithmetic, D65→XYZ white-point recovery,
and Jakob-Hanika round-trip for sRGB primaries. Nothing in the
renderer, any material, integrator, or pass is integrated yet — this is
scaffolding. `spectral.h` is kept untouched; unification happens in
pkg11 or a later cleanup package.

---

## Context

Pillar 2 rewrites Astroray's light transport from RGB to spectral,
following PBRT v4 / Mitsuba 3. The foundational types land here and
flow through every material, integrator, env map, and pass migrated in
pkg11–pkg14. Getting the type design wrong costs weeks downstream.

pkg10 is Phase 2A of the Pillar 2 roadmap: scaffolding only, no
integration. The spectral path tracer is pkg11; material migration is
pkg12–13; spectral env map is pkg14.

---

## Reference

- Design doc: `.astroray_plan/docs/spectral-core.md §Design`
- External refs: `.astroray_plan/docs/external-references.md §2`
- PBRT v4 `src/pbrt/util/spectrum.h/.cpp` — structural template only
  (Apache 2.0; project policy is to port design, not vendor code)
- Mitsuba 3 `src/librender/spectrum.cpp` — cross-reference
- Jakob-Hanika coefficient tables — Zenodo (ship in `data/spectra/`)
- CIE 1964 10° standard observer CMF — http://cvrl.ucl.ac.uk/
- D65 standard illuminant — CIE publication, public domain
- simple-spectral (geometrian, GitHub) — minimal LUT reader reference
- Colour-Science Python (BSD-3) — offline test-value oracle

---

## Prerequisites

- [ ] pkg06 is done; Pillar 1 complete.
- [ ] `main` is up to date with remote.
- [ ] Build is green on `main`: `cmake -B build && cmake --build build -j && pytest tests/ -v`.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/spectrum.h` | Public types: `SampledWavelengths`, `SampledSpectrum`, `RGBAlbedoSpectrum`, `RGBUnboundedSpectrum`, `RGBIlluminantSpectrum`; constants `kSpectrumSamples`, `kLambdaMin`, `kLambdaMax`. |
| `src/spectrum.cpp` | Out-of-line members, Jakob-Hanika LUT singleton loader, CIE 1964 10° `toXYZ`, D65 SPD sampler, LUT file discovery via `ASTRORAY_DATA_DIR`. |
| `data/spectra/rgb_to_spectrum_srgb.coeff` | Binary Jakob-Hanika LUT (Zenodo). Attribution in `THIRD_PARTY.md`. |
| `data/spectra/cie_cmf.inc` | `constexpr` arrays for CIE 1964 10° x̄ ȳ z̄, 1 nm sampling, 360–830 nm. |
| `data/spectra/illuminant_d65.inc` | `constexpr` array for D65 SPD, matched to CMF grid. |
| `tests/test_spectrum.py` | pytest coverage (arithmetic, D65→XYZ, RGB round-trip, LUT loader errors, registry unchanged). |
| `tests/data/spectrum_reference.json` | Offline-generated (Colour-Science) expected values. |
| `scripts/generate_spectrum_reference.py` | Repeatable script that regenerates the reference JSON. Documents the Colour-Science pinned version. |
| `THIRD_PARTY.md` | Provenance and license text for vendored data files and existing `stb_image*` headers. |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add `astroray_core_impl` STATIC lib containing `src/spectrum.cpp`. Link into `raytracer_standalone`, `astroray` (Python module), `raytracer_blender`, and `astroray_plugins`. Set `ASTRORAY_DATA_DIR` compile definition pointing at source-tree `data/`. Add an install rule for `data/spectra/*` under `share/astroray/`. |
| `module/blender_module.cpp` | Expose `SampledWavelengths.sampleUniform`, `SampledSpectrum` arithmetic + `toXYZ`, `RGBAlbedoSpectrum`, a top-level `rgb_to_spectrum(rgb, wavelengths)` helper, and a `spectrum_lut_path()` debug function. Follow the existing `m.def` pattern. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg10 complete when done; add pkg11 to "Active packages". |
| `CHANGELOG.md` | Add a pkg10 entry under `[Unreleased]` starting a new "Pillar 2" section. |

### Files explicitly NOT touched

- `include/astroray/spectral.h` — GR renderer still depends on it; deprecation is a later package.
- `include/raytracer.h`, `include/advanced_features.h` — deferred texture class bodies stay put.
- Any `plugins/**/*.cpp` — pkg10 does not change plugin behaviour.
- `include/astroray/integrator.h` — `sampleSpectral` default still uses legacy `SpectralSample`; pkg11 migrates.

### Key design decisions

1. **Port design, do not vendor PBRT code.** Per project policy in `external-references.md`. Type shape, method names, and math mirror PBRT v4 but each line is Astroray-native.
2. **CIE 1964 10° observer in new `spectrum.h`.** Per spec. The existing `spectral.h` keeps its 1931 2° CMF — the GR renderer depends on it and the two pipelines are deliberately orthogonal in pkg10.
3. **Hybrid representation:** `SampledSpectrum` holds 4 point-sampled values at runtime; RGB inputs are upsampled to sigmoid coefficients via Jakob-Hanika at construction and sampled on demand.
4. **LUT singleton with lazy load.** First access opens `data/spectra/rgb_to_spectrum_srgb.coeff`, memoizes the parsed table, throws a clear error on malformed files. No automatic download.
5. **Float precision throughout.** GR uses double; rendering math uses float — this is the rule in the project. `kSpectrumSamples=4` constant, `kLambdaMin=360.0f`, `kLambdaMax=830.0f`.
6. **Python bindings surface.** Full type surface (sampleUniform, arithmetic, toXYZ, RGBAlbedoSpectrum, rgb_to_spectrum helper) — enables granular pytest coverage.
7. **Data file placement.** `data/spectra/` directory at repo root. LUT loader finds it via `ASTRORAY_DATA_DIR` compile definition pointing at the source tree; install rule copies to `share/astroray/spectra/` for installed builds. An env var `ASTRORAY_DATA_DIR` override supported for relocated runs.
8. **No new runtime dependencies.** Python tests depend on `numpy` (already present). The offline reference generator uses `colour-science` but writes a static JSON — tests load the JSON, not the library.

---

## Acceptance criteria

- [ ] `include/astroray/spectrum.h` defines the five spec types, free of transitive `raytracer.h` cycles.
- [ ] `src/spectrum.cpp` builds cleanly on MinGW + MSVC + clang.
- [ ] `data/spectra/rgb_to_spectrum_srgb.coeff` committed; `THIRD_PARTY.md` lists provenance and Apache-2.0 NOTICE text.
- [ ] CIE 1964 10° CMF and D65 SPD embedded as `constexpr` arrays.
- [ ] Python bindings import cleanly; `astroray.rgb_to_spectrum([1,1,1], [450,550,620,720])` returns finite floats.
- [ ] `tests/test_spectrum.py` passes — D65 SPD → XYZ matches (0.9504, 1.0, 1.089) within 1%, sRGB primaries round-trip via Jakob-Hanika within 1% of Colour-Science reference.
- [ ] All previously-passing tests still pass (169 + new).
- [ ] Cornell box smoke render at 32 spp is pixel-identical to the pre-pkg10 baseline.
- [ ] No changes to any file under `plugins/`, and no signature change in `raytracer.h` / `advanced_features.h` / `integrator.h` / `pass.h`.
- [ ] Commit history follows the plan's granularity (docs → data → types → LUT → bindings → tests → changelog).

---

## Non-goals

- No integration into `pathTrace`, `Material::eval`, `sampleDirect`, env map, or any plugin. That is pkg11–pkg14.
- No deprecation or removal of `spectral.h`.
- No spectral AOV pass. Separate plugin, later package.
- No Hošek-Wilkie, no Tódová-Wilkie, no measured-BRDF loader.
- No performance tuning. pkg10 is correctness-first.
- No more than 4 samples. `kSpectrumSamples = 4` is a constant; tuning is a non-goal per spec.
- No RGB → ACES or Rec. 2020 upsampling tables in pkg10. sRGB only.
- No changes to the deferred texture class bodies in `raytracer.h` / `advanced_features.h`.

---

## Progress

- [x] Branch `pkg10-spectral-types` from `main`.
- [x] Write this package file from TEMPLATE.md.
- [x] Create `THIRD_PARTY.md`.
- [x] Acquire and commit Jakob-Hanika sRGB LUT (simple-spectral mirror; Zenodo-equivalent data).
- [x] Generate `data/spectra/cie_cmf.inc` (CIE 1964 10°).
- [x] Generate `data/spectra/illuminant_d65.inc`.
- [x] Implement `include/astroray/spectrum.h`.
- [x] Implement `src/spectrum.cpp` with LUT loader + toXYZ.
- [x] Wire CMake (`astroray_core_impl` lib, `ASTRORAY_DATA_DIR`, install rule).
- [x] Add Python bindings.
- [x] Generate `tests/data/spectrum_reference.json` via Colour-Science.
- [x] Write `tests/test_spectrum.py`.
- [x] Build + run full pytest (189 passed, 1 skipped; no regressions).
- [x] Update `.astroray_plan/docs/STATUS.md` and `CHANGELOG.md`.
- [ ] Commit per granularity plan; push branch.
- [ ] Open PR against `main`.

---

## Lessons

- **cvrl.ucl.ac.uk was unreachable from the build environment** during this
  session, so the CIE 1964 10° CMF came from the `colour-science` 0.4.7
  Python package (public-domain CIE data, mirrored faithfully). The
  generator script documents both the primary source and the mirror so
  future refreshes know where to look.
- **Mitsuba 3 does not ship the sRGB Jakob-Hanika `.coeff` binary** at
  the path I first guessed — the simple-spectral repo does (MIT-licensed
  wrapper around the Apache-2.0 data), so that is what the plan and
  `THIRD_PARTY.md` reference.
- **D65 under the 1964 10° observer has tristimulus ≈ (0.9481, 1.0,
  1.0731)**, not the familiar 2° values (0.9504, 1.0, 1.089). The
  whitepoint test asserts against the 10° numbers; this caught a subtle
  early attempt to compare against the 2° reference.
- **Jakob-Hanika coefficient lookup requires `z` to index the non-uniform
  `scale[]` axis, not the largest-channel value directly.** The
  generator and the C++ runtime both handle this via the same
  monotonic-search idiom so the offline reference JSON matches the
  runtime output to ≤5e-4.
- **`pybind11/operators.h` is a separate header** from `<pybind11/stl.h>`
  — needed explicitly to bind `SampledSpectrum` arithmetic overloads.
- **`ASTRORAY_DATA_DIR` as a compile definition plus env-var override**
  is the cleanest path discovery pattern: the in-tree build points at
  the source `data/` directory, installed deployments can be relocated
  by setting the env var, and a relative fallback keeps `pytest` and
  ad-hoc `python -c` sessions working when run from the repo root.
