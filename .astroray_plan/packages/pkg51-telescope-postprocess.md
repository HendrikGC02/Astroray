# pkg51 — Synthetic Telescope Observations

**Pillar:** 4
**Track:** A
**Status:** paused — Pillar 4 (Stage 3); merged with pkg133 and rewritten 2026-09-22
**Estimated effort:** 1 session (design); phases ship as separate bounded implementation packages
**Depends on:** pkg243, pkg251

---

## Goal

**Before:** Astroray has no instrument model: it samples path wavelengths uniformly over the
band, outputs one broadband image, and has no PSF, per-channel detector response or photon counts.

**After:** One declared instrument pipeline in fixed dependency order — trusted spectral
output (pkg243) → flux-normalized radiance microbins (render-time, per path wavelength,
Mitsuba 3 `specfilm` importance-sampling mechanism) → chromatic optics (per-microbin PSF
from STPSF/WebbPSF FITS cubes) → detector statistics (filter throughput T(λ) × QE(λ)
applied exactly once, collecting area, pixel solid angle, exposure, photon-energy
conversion, Poisson + read + dark). SRF channel layers are derived outputs only. This spec
merges pkg51 and pkg133 into one design with separate bounded implementations.

**First measurable deliverable:** a synthetic observation of the Track N Case-B hydrogen
slab through one declared instrument (filter SRF + per-band PSF + exposure). The
**response-corrected integrated energy-radiance ratio** must recover the literature
Hα/Hβ = 2.86 (Case B, Tₑ = 10⁴ K, nₑ = 100 cm⁻³; A&A 2021 Case-B grid) as a mean over
realisations with its 95 % CI wholly inside ±2 %; detector counts/SNR are reported
separately. Its electron statistics must match the declared exposure. **Response-weighted
radiance alone is NOT a photon-count model.**

---

## Context

Stage 3 of `stage-plan-2026-09-22.md` requires one instrument design with separate
implementations, gated on pkg243 — still open on pkg251, so no calibrated or absolute claim
is possible. The render-time half (pkg133) was never implemented; the image-space half
(pkg51) was outreach-grade only, so the Track N nebula deliverable cannot be observed through
an instrument. pkg133's design merges here as Phase 1, preserving "separate implementations".

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: Astra turn-2 review amendments applied (planning session).
- 2026-09-22: Codex Terra review defects applied (planning session).
- 2026-09-22: Astra turn-4 sign-off discrepancies closed (planning session).
- 2026-09-12: pkg133 triage — no SRF/`specfilm` spectral-sensor code exists in the repo.
- pkg243 (raw band output + provenance) is open and depends on pkg251; no band contract is landed.
- `include/astroray/pass.h` (pkg06) and `include/astroray/fits_io.h` (pkg47) already exist and are reusable.

---

## Reference

- Design docs: `.astroray_plan/docs/astrophysics.md §4.7` (old PSF/noise scope);
  `.astroray_plan/docs/stage-plan-2026-09-22.md §3–§4`;
  `.astroray_plan/docs/pillar4-data-io-research.md` (units, provenance, resampling loss);
  `.astroray_plan/docs/atomic-line-broadening-research.md` (narrow lines vs band sampling).
- Mitsuba 3 films (`specfilm`): https://mitsuba.readthedocs.io/en/stable/src/generated/plugins_films.html (BSD-3).
- STPSF: https://stpsf.readthedocs.io/en/latest/usage.html; WebbPSF: https://webbpsf.readthedocs.io/ (BSD).
- Per-band PSF weighting: STPSF usage docs; see also "Spectral Imaging in Production", DOI 10.1145/3450508.3464582.
- Hero-wavelength basis: Wilkie et al., EGSR 2014, DOI 10.1111/cgf.12419.
- pkg133 source record: `.astroray_plan/docs/2026-07-other-engines-research.md §3`.
- Case-B ratio: A&A 2021 grid, https://www.aanda.org/articles/aa/pdf/2021/10/aa40890-21.pdf.
- Infrastructure: `include/astroray/pass.h` (pass registry), `include/astroray/fits_io.h` (FITS cubes),
  `include/astroray/spectrum.h` (`kLambdaMin`/`kLambdaMax`).

---

## Prerequisites

- [ ] pkg251 done (band parameter reachability contract).
- [ ] pkg243 done (raw relative band output + honest provenance) — hard gate on any calibrated claim.
- [ ] pkg243 Phase 1 (scene-length units + emissivity-to-radiance contract; to be filed) done — **Phase 0/1 are BLOCKED on it.**
- [ ] pkg243 Phase 2 (observer pixel solid angle + physical radiance normalisation / detector conversion; to be filed) done — **Phase 3 is BLOCKED on it.**
- [ ] pkg47 done (FITS loader) for PSF cubes — done.
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/passes/telescope.cpp` | Merged instrument pass: radiance microbins, chromatic optics, detector statistics (phases land incrementally). |
| `tests/test_telescope.py` | Numeric gates per phase (flat field, PSF FWHM, flux conservation, SNR, reproducibility). |
| `scripts/generate_psf_cube.py` | STPSF/WebbPSF → wavelength-tagged per-band PSF FITS cube generator. |
| `tests/data/test_psf_gaussian.fits` | Tiny synthetic Gaussian PSF cube for tests (no STPSF required). |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/spectrum.h` | Add SRF channel tabulation + combined CDF over the 360–830 nm grid (CIE 1931 is the observer, not the emissivity grid); add flux-normalized radiance-microbin tabulation. |
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Preserve per-band radiance to the film as flux-normalized microbins; no display transform before the raw channel (pkg243 contract). |
| `src/io/exr_writer.h` | Write one named float layer per radiance microbin; SRF channel layers are derived outputs. |
| `module/blender_module.cpp` | Expose SRF channels, PSF cube path, exposure and detector parameters. |
| `blender_addon/__init__.py` | Instrument section: instrument/filter picker, PSF file, exposure, detector parameters. |

### Key design decisions

- **Two execution domains.** Radiance-microbin accumulation is render-time (film, per path
  wavelength); PSF convolution and detector statistics are image-space, per microbin.
  pkg133's boundary is preserved: the film feeds cleaner spectral input; it does not do PSF or noise.
- **Never collapse bands.** Spectral information stays per microbin through PSF + detector; a
  wavelength-dependent, spatially varying PSF cannot be recovered from one broadband image
  (STPSF weighting). The multichannel EXR of flux-normalized microbins is the hand-off.
- **Response applied exactly once.** T(λ) and QE(λ) enter only inside the Phase 3 detector
  integral, over flux-normalized radiance microbins. Phase 1 never emits response-weighted
  counts and SRF channel layers are derived outputs, so no double QE/throughput.
- **No calibration before pkg243.** Phases 0–1 emit relative band radiance with provenance;
  absolute electron counts wait for Phase 3 and a landed pkg243 contract.
- **Ordering.** render → spectral output (pkg243) → radiance-microbin accumulation →
  per-microbin PSF → detector integration (T·QE once) → (optional) denoise. Denoising a
  noisy synthetic observation is physically questionable; document that the user should disable OIDN.
- **Reuse, do not reinvent.** Use `include/astroray/pass.h` (no parallel pass API) and
  `include/astroray/fits_io.h`; fall back to a Gaussian FWHM = 1.22 λ/D only when no cube is supplied.

#### Phase 0 — Contract audit (blocked on pkg243)

Audit the pkg251/pk243 band contract: raw relative band quantity preserved before any
display transform; wavelength grid tied to `kLambdaMin=360` / `kLambdaMax=830` nm; the
flux-normalized radiance-microbin tabulation defined over that grid, with SRF channels
(filter × QE) as derived outputs. No photon counts claimed.
**Acceptance (numeric):** a flat-spectrum render round-trips raw floats > 1.0 and equals
the analytic flat band integral within 0.5 % relative; no display transform touches it.

#### Phase 1 — Radiance-microbin accumulation (pkg133 merge)

Port Mitsuba 3 `specfilm`'s importance-sampling mechanism: build one combined continuous
distribution over the union of N SRF channels by inverse-transform sampling;
importance-sample path wavelengths from it; deposit **flux-normalized radiance** into
wavelength microbins (bin width fine enough for Phase 2), keeping the deposit
hero-wavelength-aware (Wilkie 2014) so the existing spectral pdf stays unbiased. No T(λ)
or QE(λ) is applied here. N microbins → N EXR layers; SRF channel layers are derived by
response-weighting afterwards, never deposited directly.
**Acceptance (numeric):** a flat full-band SRF reproduces the uniform-sampling render
within MC noise (≤ 1 σ over ≥ 64 spp); a narrow-band SRF reaches target relative error in
≤ 1/4 the samples of uniform sampling (report the measured factor); microbin radiance is
flux-normalized (total invariant to bin width, < 1 % on halving).

#### Phase 2 — Chromatic optics (per-band PSF)

Convolve each radiance microbin independently with its PSF slice loaded from a
wavelength-tagged STPSF/WebbPSF FITS cube (`include/astroray/fits_io.h`); each slice carries
an explicit wavelength coordinate, is interpolated in λ to the microbin wavelength (linear),
resampled onto the detector pixel grid, and normalized to unit sum (flux-conserving) before
convolution; zero-pad to avoid wrap-around. Spectral effects are never recovered from one
broadband image.
**Acceptance (numeric):** PSF FWHM matches the STPSF cube within 5 %; a delta source
convolves to the PSF with unchanged centroid; per-microbin outputs differ exactly where the
cube differs; encircled energy is preserved and a flat-field flux-conservation test holds
(summed convolved flux equals input within 1 %).

#### Physical normalisation bridge

pkg243 exports RELATIVE band radiance only. pkg243 **Phase 1** (Stage 1c prerequisite) fixes
the scene-length units and emissivity-to-radiance contract; pkg243 **Phase 2** (Stage 3
bridge) supplies only the observer pixel solid angle Ω_pix and the physical radiance
normalisation / detector conversion (per-nm I_λ, W m⁻² sr⁻¹ nm⁻¹; Phase 3 fixes the nm↔m
units). Exposure and collecting area cannot calibrate an arbitrary scalar. **Phase 3 is
BLOCKED on pkg243 Phase 2; Phase 0/1 are blocked on pkg243 Phase 1.**

#### Phase 3 — Detector statistics (photon-count model)

Physical normalisation per band, chromatic form:

  μ_e(x) = t · A · Ω_pix · ∫ [I_λ ∗ P_λ](x) · T(λ) · QE(λ) · λ/(h c) dλ

where ∗ is convolution with the wavelength-dependent PSF P_λ applied **before** spectral
integration, T(λ) is optical throughput/filter transmission and QE(λ) the detector quantum
efficiency. **Wavelength units (frozen 2026-09-22, lead may adjust):** λ and dλ are SI
metres throughout — the 360–830 nm microbin grid converts as dλ = dλ_nm × 10⁻⁹ m and
per-nm radiance as I_λ = I_λ,nm × 10⁹ W m⁻² sr⁻¹ m⁻¹; h = 6.62607015×10⁻³⁴ J s and
c = 2.99792458×10⁸ m s⁻¹ (SI 2019 exact), so λ/(h c) is photons J⁻¹. Equivalently in the
nm domain, μ_e = t · A · Ω_pix · ∫ [I_λ ∗ P_λ] · T · QE · (λ_nm · K) dλ_nm with
K = 10⁻⁹/(h c) = 5.034117×10¹⁵ (J nm)⁻¹; the analytic-count test below MUST use this same
conversion, so a 10⁹ unit slip fails it rather than hiding in a per-nm scalar.
T(λ) and QE(λ) are applied **here and only here** (Phase 1 deposited
flux-normalized radiance). A broad SRF-integrated image cannot receive the correct
chromatic PSF afterwards, so Phase 1 must preserve spectral bins fine enough for Phase 2;
add a **spectral-bin convergence test** (halving the bin width changes μ_e by < 1 %).
Three quantities stay distinct: **incident photons**, **detected electrons** (μ_e above),
and **ADU** (gain applied); tests name which one they check. Because QE is already inside
μ_e, detected electrons are sampled directly as `Poisson(μ_e)` (equivalently, sample
incident photons then binomial-thin by QE); read noise and dark current are added in
electrons (Gaussian read, Poisson dark), then converted **once** by gain to ADU, with
collecting area, pixel solid angle, exposure time and photon-energy conversion explicit
parameters.
**Acceptance (numeric):** a flat field of known spectral radiance yields the analytic
detected-electron count within 1 % using the metre/nm conversion above (a 10⁹ unit slip
must fail it); SNR ∝ √t in the photon-noise-dominated regime (fit
exponent 0.5 ± 0.02); read and dark add in quadrature to the analytic σ; identical seed
reproduces identical noise; the spectral-bin convergence test passes (< 1 % on halving);
each test names photons, electrons or ADU.

#### Phase 4 — Declared-instrument observation

Wire Phases 1–3 to the Blender addon as the declared instrument and produce the first
measurable deliverable figure (Track N Case-B slab).
**Acceptance (numeric, ENSEMBLE statistics; Stage 3 contract):** with renderer MC noise
removed (noise-free converged input; `add_noise` only in the detector stage), the per-pixel
electron counts over a frozen design — 1000 realisations, 32 equal-width electron-count
bins spanning μ_e ± 6σ, pooled so every bin has expected occupancy ≥ 5, dof = pooled
bins − 1 (frozen 2026-09-22, lead may adjust) — match the declared Poisson+read+dark model
under a goodness-of-fit test at α = 0.01 (χ² bounds from the frozen dof, or a calibrated
simulation-based test, so a correct simulator is rejected at a known rate). Line recovery
is the **response-corrected integrated energy-radiance ratio** Hα/Hβ = 2.86 as a mean over
realisations with its 95 % CI wholly inside ±2 %; detector counts/SNR are reported
separately; linear scaling with path length.

---

## Acceptance criteria

- [ ] `TelescopeObservation` registered via the `include/astroray/pass.h` registry; no parallel pass API.
- [ ] Flat field of known radiance yields the analytic **detected-electron** count within 1 % (Phase 3); the chain keeps incident photons, detected electrons and ADU distinct, and every test names the quantity it checks.
- [ ] Spectral-bin convergence: halving the bin width changes μ_e by < 1 % (Phase 3).
- [ ] T(λ) and QE(λ) applied exactly once (Phase 3); SRF channel layers are derived outputs, never spectral inputs.
- [ ] PSF FWHM matches the STPSF cube within 5 %; delta convolution preserves centroid; flat-field flux conservation holds within 1 % (Phase 2).
- [ ] Narrow-band SRF reaches target error in ≤ 1/4 the uniform-sampling sample count, reported (Phase 1).
- [ ] Flat full-band SRF reproduces today's output within MC noise (unbiased; Phase 1).
- [ ] Same seed reproduces identical noise; `add_noise=false` yields a noise-free convolved image.
- [ ] With noise-free converged input and detector-only noise, the frozen realisation/binning design matches the declared Poisson+read+dark model under a goodness-of-fit test at α = 0.01; the response-corrected integrated energy-radiance Hα/Hβ = 2.86 has its 95 % CI wholly inside ±2 % (detector counts/SNR reported separately).
- [ ] Blender addon exposes all instrument parameters.
- [ ] All existing tests pass; ≥ 8 new tests; per-phase visual output saved and inspected.

---

## Non-goals

- Do not make instrument-calibrated or absolute claims before pkg243 lands.
- No detector cosmetics: bad pixels, persistence, CTE, non-linearity, cosmic rays, flat fielding, bias.
- No multi-filter RGB compositing; output is per-band layers only.
- No atmospheric seeing, adaptive optics or coronagraphs; space-based diffraction-limited PSF only.
- Do not require WebbPSF/STPSF as a build or test dependency.
- No X-ray microphysics, diffraction gratings (#141) or cluster lensing; deferred until a science case names them.
- No hydrodynamics.

---

## Progress

- [ ] Phase 0 — contract audit (blocked on pkg243).
- [ ] Phase 1 — radiance-microbin accumulation (pkg133 merge).
- [ ] Phase 2 — chromatic optics (per-band PSF).
- [ ] Phase 3 — detector statistics (photon-count model).
- [ ] Phase 4 — declared-instrument observation + first deliverable figure.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*
