# pkg214 — Sodium-vapor lamp preset emits no light (narrow D-line aliased to zero)

**Pillar:** 3 (light transport / spectral rendering)
**Track:** A
**Status:** open (filed 2026-08-21).
**Estimated effort:** S–M (spectral-profile data-build fix + regenerate `profiles.bin` + regression test).
**Depends on:** none.

## Goal

The `sodium_vapor` preset lamp renders **black** (emits no light), while `mercury_vapor` renders correctly. Make the sodium lamp emit visible **amber** light (`>0` linear RGB, `R > G > 3·B`) through the CPU multiwavelength path.

## Context

**Root cause — a narrow emission line aliased to a single grid bin that the wavelength sampler misses:**

- `scripts/data/build_spectral_profiles.py:620` `_atomic_lines` deposits each atomic line into the **single nearest 5 nm grid bin** (`LAMBDA_STEP = 5`): `idx = round((wl_nm - LAMBDA_MIN)/LAMBDA_STEP); r[idx] += intensity`.
- Sodium's two D-lines (588.995 nm, 589.592 nm — `:683`) are 0.6 nm apart, so **both round to the same ~590 nm bin**. After `mat_ls` peak-normalisation (`:590`), the sodium SPD is a single 5 nm-wide spike of value 1.0 at 590 nm and **exactly zero at every other wavelength**.
- `mercury_vapor` (`:688–705`) works because, on top of its discrete lines, it adds a **flat 50-unit continuum across 400–700 nm** (`:695–697`) → ~5 % everywhere after normalisation → every sampled hero wavelength catches nonzero emission. Sodium has **no continuum**, so it is emissive only in that one bin.
- The multiwavelength path tracer samples the emission SPD at a handful of hero/stratified wavelengths spread across [380, 780] nm. A single 5 nm feature at 590 nm is missed by essentially every sample (`src/light_sampler.cpp:55–67` documents this exact failure: "a sodium-vapor lamp whose SPD is a ~589 nm spike, so the u=0.5 hero wavelengths {380,480,580,680} all read ~0"). The emitted radiance integrates to ~0 → black.
- pkg195 already fixed light **selection** (the `totalPower == 0` uniform fallback at `light_sampler.cpp:55–67` keeps the lamp in the CDF), but the emission **radiance** returned at the sampled wavelengths is still zero — selection ≠ emission.

**So the defect is in the stored profile, not the sampler:** a sub-grid-resolution line cannot be integrated by a finite-sample MC/Riemann wavelength sweep. The fix is to represent each atomic line at (at least) the render's spectral sampling resolution.

**Fix forks considered (surface, don't force):**
- *Broaden the atomic lines to a finite, energy-conserving width in `_atomic_lines`* — **chosen.** Localised data-build change; conserves total energy; preserves the D2:D1 = 2:1 ratio and the ~589 nm centroid (amber); fixes all atomic-line lamps by one mechanism; no engine change; no overlap with in-flight sampler work.
- *Emission-line importance sampling (draw λ ∝ emission SPD) in the wavelength sampler* — rejected for this package. More correct in the limit, but a CPU+GPU byte-mirrored sampler change that **overlaps pkg206** (luminance-weighted hero-wavelength sampling, PR #627) and risks double-ownership of the same code. Note it as the general-case follow-up, not the fix here.

Honest tradeoff (CLAUDE.md §1): broadening widens the line beyond its sub-nm physical linewidth. That is acceptable and standard — the pipeline stores/samples spectra on a 5 nm grid, so a sub-bin feature is unrepresentable regardless; broadening to the grid/sampling resolution is *matching the line to the renderer's spectral resolution*, not a physics claim about the lamp. State this explicitly in the code comment and the research note.

## Reference

- `scripts/data/build_spectral_profiles.py:620` (`_atomic_lines`, nearest-single-bin), `:678–686` (sodium), `:688–705` (mercury + continuum), `:583–597` (`mat_ls` peak-normalisation).
- `src/light_sampler.cpp:55–67` — pkg195 degenerate-CDF fallback + the comment naming the exact zero-emission failure mode.
- `data/spectral_profiles/profiles_metadata.json` — `sodium_vapor` (~line 338), `mercury_vapor` (~line 345).
- Tests: `tests/test_spectral_profiles.py` (`test_sodium_vapor_d_line_concentration`, `test_mercury_vapor_line_peaks`), `tests/test_pkg195_stage_b_spectral_lamp.py` (`test_b1_sodium_lamp_is_amber`, `test_b2_cie_f2_differs_from_sodium`).
- Memory: `general-photon-loop-needs-solid-glass` (always visually verify spectral renders); `gamma-furnace-cannot-detect-energy-gain` (render LINEAR).

## Specification

1. **Invoke the `cite-algorithm` skill BEFORE writing code** (CLAUDE.md §6). Cite a canonical emission-line broadening / line-shape source (Gaussian Doppler / Voigt line profile) and justify the chosen FWHM against the 5 nm grid + the render's wavelength-sampling resolution. Save a research note to `.astroray_plan/docs/` and cite it inline in `build_spectral_profiles.py`.
2. In `_atomic_lines` (`build_spectral_profiles.py:620`), replace the single-nearest-bin deposit with an **energy-normalised Gaussian** of a stated FWHM (chosen so the doublet spans **≥3 grid bins**, i.e. FWHM on the order of 10–15 nm at the current 5 nm grid). Preserve each line's relative intensity as the **area** under its Gaussian (so the D2:D1 = 2:1 ratio and total energy are conserved). The two Na D-lines, 0.6 nm apart, merge into a single ~589 nm feature at any reasonable FWHM — that is correct (low-pressure sodium reads as one unresolved doublet).
3. Regenerate `data/spectral_profiles/profiles.bin` by running `build_spectral_profiles.py`, and commit the regenerated binary (and any regenerated `profiles_metadata.json`). Register nothing new in `scripts/README.md` (existing script, extended in place — CLAUDE.md §5b).
4. Leave mercury's continuum untouched. Broadening its discrete lines via the same `_atomic_lines` change is fine (it already renders via the continuum); the goal is a correct mechanism for **all** atomic-line lamps, not a sodium special-case.
5. **No engine / C++ change.** If implementation-time inspection shows the `measured_spd` sample path *also* drops narrow features (e.g. nearest-neighbour LUT lookup in `emission_spectrum`), note it — but broadening resolves the black render under either nearest or linear interpolation, so no sampler change is in scope here.

## Acceptance criteria

- [ ] `cite-algorithm` invoked; research note (line-shape choice + FWHM justification vs grid/sampling resolution) lands in `.astroray_plan/docs/`; the broadening is cited inline in `build_spectral_profiles.py`.
- [ ] `profiles.bin` regenerated & committed; `astroray.spectral_profile_reflectance("sodium_vapor", λ) > 0` for `λ` across **≥3 grid bins** centred near 589 nm (proves the line now spans multiple bins).
- [ ] **Emission gate (regression test — strengthen `test_b1_sodium_lamp_is_amber`):** white sphere + `sodium_vapor` point lamp, CPU multiwavelength, **LINEAR**, seed-pinned: mean linear RGB above an explicit positive floor (e.g. `R > 1e-3`) **AND** amber (`R > G > 3·B`). Add the explicit `>0` floor (the current test infers non-zero only via the ratio).
- [ ] `test_b2_cie_f2_differs_from_sodium`, `test_sodium_vapor_d_line_concentration`, and `test_mercury_vapor_line_peaks` still pass (the ~589 nm energy concentration must survive the broadening — state the tolerance).
- [ ] **No mercury regression:** `mercury_vapor` mean linear RGB within an MC-noise band of its pre-fix value (per-channel mean-ratio, memory `ssim-wrong-gate-for-independent-rng`).
- [ ] CI green on all matrix jobs (`gh run view` on HEAD).

## Non-goals

- **No emission-line importance sampling** in the wavelength sampler — that overlaps pkg206 and is the general-case follow-up, not this fix.
- **No change to mercury's continuum** and **no new lamp presets.**
- **No GPU-specific work.** `measured_spd` is CPU-exact; the GPU RGB-approximates non-RGB emission (`DATA_PT_custom_raytracer_light` already warns of this) — improving GPU narrow-line fidelity is out of scope. The profile-data fix flows to both backends via the shared `profiles.bin`.

## Progress

_(none yet)_

## Lessons

_(none yet)_
