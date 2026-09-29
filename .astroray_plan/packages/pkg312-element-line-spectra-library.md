# pkg312 — Element line-spectra library (NIST ASD, LTE, Voigt) + Element Emission and Spectrum Mix nodes

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 2–3 sessions (~8 h): data pipeline + bake ~4 h, nodes + registration ~2 h, tests + evidence ~2 h
**Depends on:** pkg195, pkg218, pkg222

---

## Goal

Before: Astroray ships 7 emission profiles (CIE F2/F3, three LEDs, Na, Hg),
hand-synthesised from a few NIST lines. There is no way to author "neon at
3000 K" or "70 % Na + 30 % Hg".

After:
- A versioned line library (NIST ASD) covers H–Zn plus selected heavy
  elements (Sr, Ba, Kr, Xe, Hg, Cs, Rb, Li, In, Tl), neutral and singly
  ionised, 300–2500 nm.
- An offline, cited bake turns (element, ion stage, T, P) into a
  unit-integral LTE emission profile with Voigt line shapes.
- Two addon nodes, **Element Emission** and **Spectrum Mix** (weights +
  normalisation), produce runtime profiles that lamps and emission shaders
  already consume through `MeasuredSPD`.
- No engine change.

---

## Context

Owner 2026-09-29: "we will need plenty more — probably one for pretty much
every element and/or some molecules — which can be combined and scaled to
create complex emission and absorption spectra." This is theme 3 Phase 1
(`product-themes-plan-2026-09-29.md` §3). It is product-now (gas-discharge
signage, flames, arcs, street lamps) and science substrate (pkg46 line
emission and pkg51 narrowband filters reuse the line library). Absorption
(Phase 2) and molecules (Phase 3) are separate packages; molecular licences
are an owner decision. Sonnet 5.5 lane, Terra review; run `cite-algorithm`
before writing the bake.

**LTE only.** Boltzmann populations at T suit lamps, flames and arcs. Nebular
Case-B recombination ratios are pkg45/pkg46's domain. The node's tooltip and
docs must say so.

---

## Evidence

- 2026-09-29: `data/spectral_profiles/profiles.bin` ASPR v1, 47 entries (40 reflectance, 7 emission), 300–2500 nm @ 5 nm (`scripts/data/spectral_profile_format.md`).
- 2026-09-29: `scripts/data/build_spectral_profiles.py` ~640–680 broadens hand-typed NIST lines into area-normalised Gaussians at bake time.
- 2026-09-29: `EmissionSpectrum::Composite` (`include/astroray/emission_spectrum.h:79`) is base × RGB filter only, with no weighted sum. Runtime profiles go through `register_spectral_profile` (process-wide singleton, memory `spectral-profile-edit-footguns`).

---

## Reference

- Plan: `.astroray_plan/docs/product-themes-plan-2026-09-29.md` §3; design `spectral-node-system-design-2026-08.md` §2.3, §3.4 (sources and storage); `atomic-line-broadening-research.md`.
- NIST Atomic Spectra Database (Kramida, Ralchenko, Reader & NIST ASD Team), US-gov public domain; cite the ASD version and retrieval date. Fields: λ (vacuum/air flagged), A_ki, g_k, E_k.
- LTE line emissivity: ε_ul ∝ (g_u A_ul / λ_ul) · exp(−E_u / kT) in energy units (Rybicki & Lightman, *Radiative Processes*, §10). Every line in one spectrum shares the partition function, so it cancels on normalisation.
- Doppler width σ_λ = (λ₀/c)·√(kT/m); Voigt via Faddeeva `wofz` (`scipy.special.voigt_profile`, BSD-3). The Lorentz width is the natural width plus a user pressure-broadening γ(P) (van der Waals scaling with a documented default); pressure is an approximation flag, not a physics claim.
- Air/vacuum conversion: Ciddor 1996 / Morton 2000 (state which in the code).
- Existing precedent: pkg214 (sodium), pkg222 (atomic-line lamp SPD chromaticity).

---

## Prerequisites

- [ ] `cite-algorithm` research note written: `.astroray_plan/docs/pkg312-line-library-research.md`.
- [ ] pkg311's Add-menu categories on main, or rebase onto them (same file).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `scripts/data/fetch_nist_asd_lines.py` | Reproducible NIST ASD fetch (element, ion stage, λ range, A_ki > 0), cached to `data/spectral_lines/raw/` with retrieval metadata |
| `data/spectral_lines/lines_v1.json` | Compact line library: per species `{lambda_vac_nm, A, g_u, E_u_eV, mass_amu}`, versioned, with provenance header |
| `data/spectral_lines/SOURCES.md` | Licence, citation, ASD version and retrieval date per species |
| `scripts/data/bake_line_spectrum.py` | Pure function (species, T, P, grid) → unit-integral profile on the ASPR grid, with area-conserving binning; also imported by the addon |
| `tests/test_pkg312_line_spectra.py` | Bake and node tests (see Acceptance) |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/nodes/__init__.py` | `AstrorayShaderNodeElementEmission` (element and ion enum from `lines_v1.json`, T, P) and `AstrorayShaderNodeSpectrumMix` (N weighted inputs, normalise toggle); both register a content-hashed runtime profile |
| `blender_addon/__init__.py` | Emission shader and light export accept the Element Emission / Spectrum Mix output as a `MeasuredSPD` |
| `scripts/build/build_blender_addon.py` | Package `lines_v1.json` and `bake_line_spectrum.py` |
| `scripts/README.md` | Register the fetch and bake scripts |

### Key design decisions

- **Engine stays unchanged.** Mixing happens at authoring time into one
  registered profile. The engine sees a normal `MeasuredSPD`, so there is no
  new `EmissionSpectrum` variant and no GPU change.
- **Profile names are content-hashed.** A registered name is
  `__line__/<sha1(species, T, P, weights, grid)>`, never keyed on `id(node)`
  (memory `id-node-cache-aliasing-blender-addon`). The singleton's
  overwrite-in-place semantics make hashing necessary for determinism.
- **Mixing semantics.** L(λ) = Σ wᵢ·Pᵢ(λ), each Pᵢ unit-integral. With
  normalise on, the result is re-normalised to a unit integral, and lamp
  Power or Strength sets the absolute scale (the existing convention).
  Reflectance profiles are rejected as Mix inputs, with a clear error.
- **Binning conserves area.** Integrate the Voigt profile over each 5 nm bin;
  do not point-sample it, or lines narrower than a bin vanish or spike.
- **Wavelengths.** Vacuum internally; convert air wavelengths from ASD
  explicitly.
- **GPU check.** Measure whether GPU emission shaders use the spectral table
  or RGB-approximate (pkg218 covered dedicated lights). If they
  RGB-approximate, the export must add a DEGRADED line, and the gap is filed
  as an issue, not fixed here.

---

## Acceptance criteria

- [ ] Line positions: for Na I, Hg I, H I, Ne I, the bin holding each of the 5 strongest lines in 300–830 nm contains the NIST λ (±1 bin), both air and vacuum cases tested.
- [ ] Unit integral within 1e-4 for every baked species at T ∈ {1500, 3000, 6000, 10000} K.
- [ ] Boltzmann test: the ratio of two isolated lines of one species versus the analytic (g A / λ)·exp(−ΔE/kT) matches within 1 % at 3 temperatures.
- [ ] Doppler test: the fitted σ of an isolated line on a 0.01 nm debug grid matches (λ₀/c)√(kT/m) within 2 %.
- [ ] Mix linearity: Mix(a·A, b·B) equals a·A + b·B (normalise off) to 1e-6; the same parameters give the same name (hash stability).
- [ ] Render: a neon-tube and a Na/Hg street-lamp scene render on CPU and GPU; CIE xy of the lamp versus the chromaticity of the baked SPD within 0.005 (CPU). GPU either matches or emits a DEGRADED line with an issue filed. PNGs inspected by Opus.
- [ ] `lines_v1.json` < 5 MB; `SOURCES.md` complete; `project_index.py lint` clean.

---

## Non-goals

- Do not add molecular data (Phase 3; owner licence decision).
- Do not implement absorption or volume σ(λ) (Phase 2).
- Do not add a finer ASPR grid or line-aware λ sampling (Phase 4, Pillar 4).
- Do not model non-LTE, Saha ionisation balance or Case-B recombination.
- Do not change engine or GPU code.

---

## Progress

- [ ] Research note (cite-algorithm)
- [ ] NIST fetch + line library + SOURCES.md
- [ ] Bake function + unit tests
- [ ] Nodes + export + packaging
- [ ] Render evidence + GPU check

---

## Lessons

*(Fill in after the package is done.)*
