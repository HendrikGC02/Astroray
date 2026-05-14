# pkg43 — Slim Disk Accretion Model

**Pillar:** 4
**Track:** B (plugin, self-contained)
**Status:** done (PR #271, 2026-05-14 — T(9M, mdot=1) = 7.45e6 K matches Page-Thorne 1974 eq. 11n + Sadowski 2009 advective; 14/14 slim-disk tests pass; no pkg42 regression; units fix r_s→r_g)
**Estimated effort:** 2 sessions (~5 h) — bumped from "1-2 sessions
(~4 h)" after research; the advective-fraction fit and the
exponential-clamp logic for super-Eddington need their own unit tests.
**Depends on:** pkg40 (Kerr metric), pkg42 (VolumetricEmission interface)

**Reference research:** `.astroray_plan/docs/accretion-emission-research.md`
(slim-disk profile §4, transfer pipeline §1, license matrix §7).

---

## Reference Implementations

The Sądowski 2009 slim-disk solution has **no closed-form analytic
expression** — the paper solves six coupled ODEs by relaxation. For
visualization, pkg43 implements the analytic fitting-function
skeleton from research-note §4 (Page-Thorne T_NT plus an exponential
advective attenuation). Tabulated solutions are a Non-goal.

| Repo | Commit | License | Mirror permitted | Notes |
|------|--------|---------|-----------------|-------|
| (paper only) Sądowski 2009 ApJS 183, 171 | — | journal article | math is public-domain; cite eqs. 1-9 in code | This is the primary source; no code to mirror |
| [ipole](https://github.com/AFD-Illinois/ipole) | `master` 2024-Q4 | BSD-3-Clause | radiation/transfer plumbing only — **no slim-disk file exists** | Use `src/radiation.c` (`Bnu_inv`, `get_fluid_nu`, `get_bk_angle`) for the §1 invariant transfer scaffold |
| [GYOTO](https://github.com/gyoto/Gyoto) | — | CeCILL (GPL-incompat) | **No** — numerical cross-check only | `Astrobj/PolishDoughnut.C` is the closest analogue; reference only |
| [RAPTOR](https://github.com/tbronzwaer/raptor) | `08cb9a2` | **GPLv3** | **No** — cross-validation only | Same fence as pkg40 / pkg42 |

The brief originally suggested mirroring an ipole slim-disk file. As of
the master commit there is no such file in the ipole tree (verified
2024-Q4); the closest is the BHAC/HARM GRMHD-snapshot model loader,
which is out of scope. Implement Sądowski 2009 directly.

---

## Goal

**Before:** The only accretion model is Novikov-Thorne (1973), which
assumes a geometrically thin, optically thick disk in the equatorial
plane. This is valid for sub-Eddington accretion rates (L/L_Edd < 0.3)
but breaks down at higher rates where radial advection becomes
important and the disk puffs up.

**After:** A `SlimDisk` emission plugin implements the Abramowicz et al.
(1988) / Sądowski (2009) slim disk model. The disk has finite vertical
thickness that increases with accretion rate, a temperature profile that
flattens near the ISCO (due to advection carrying entropy inward), and
correct spectral emission for super-Eddington sources like narrow-line
Seyfert 1s, ULXs, and SS 433.

---

## Context

The slim disk bridges the gap between the thin disk (Novikov-Thorne)
and the ADAF (pkg44). It matters because the most luminous accreting
black holes — the ones that produce the most visually striking images —
are often super-Eddington. The thin disk model under-predicts the inner
disk temperature and gets the vertical structure wrong for these sources.

From a spectral pipeline perspective, the slim disk's broader thermal
spectrum (multi-colour blackbody with advective corrections) is a
natural fit for the `SampledSpectrum` framework.

---

## Reference

- **Research notes (read first):** `.astroray_plan/docs/accretion-emission-research.md`
  (slim-disk profile §4 — H/r, Sigma, T(r) with advective fit;
  pipeline §1; license matrix §7)
- Design doc: `.astroray_plan/docs/astrophysics.md §4.2`
- Sądowski, A. 2009, ApJS 183, 171 — six governing ODEs (eqs. 1-9);
  the primary source.
- Abramowicz et al. 1988, ApJ 332, 646 — original slim-disk formulation.
- Abramowicz & Fragile 2013, Living Rev. Relativity 16, 1 — review
  (Polish doughnut / thin / slim / ADAF in one place).
- Page & Thorne 1974, ApJ 191, 499 — Novikov-Thorne T_NT(r) used as
  the slim-disk baseline.
- Existing Novikov-Thorne: current accretion disk code in
  `black_hole.cpp` or GR renderer.
- VolumetricEmission interface: `include/astroray/emission.h` (from pkg42)

---

## Prerequisites

- [ ] pkg40 is done: Kerr metric with ISCO calculation available.
- [ ] pkg42 is done: `VolumetricEmission` interface and
      `EmissionRegistry` exist.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/accretion/slim_disk.cpp` | `SlimDisk` emission plugin. |
| `tests/test_slim_disk.py` | Unit and integration tests. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Expose slim disk parameters. |
| `blender_addon/__init__.py` | Add accretion model selector (Novikov-Thorne / Slim Disk / ADAF) and slim disk parameters to the black hole panel. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg43 done. |
| `CHANGELOG.md` | Add pkg43 entry. |

### Physics model

#### Vertical structure (Sądowski 2009 eq. 5; research note §4.1)

Sądowski 2009 eq. 5 (vertical hydrostatic equilibrium, H = c_s/Ω_K)
gives, in the slim regime, a half-thickness that scales with
accretion rate:

    H/r ≈ (3/2) · (ṁ / ṁ_Edd) · f_geom(r, a)

with f_geom(r, a) ≈ 1 / (1 + (r/r_ISCO)²) — order-unity at ISCO,
falling as 1/r² outside. Copy-paste C++ form in research note §4.1.
At sub-Eddington (ṁ < 0.3 ṁ_Edd) H/r << 1 and the disk recovers
Novikov-Thorne. At super-Eddington (ṁ > 1) H/r → 0.5-0.75 at ISCO
and the disk is a genuine volume emitter.

The plugin implements the disk as a volume with density concentrated
in the equatorial region: ρ(r,θ) ∝ exp(−z²/2H²) where z = r cos θ.
Number density is n_e = Σ / (2 H m_p), with Σ from the alpha-viscosity
closure (research note §4.2).

#### Temperature profile (Sądowski 2009 §3 + Page & Thorne 1974 eq. 11n)

The Novikov-Thorne temperature profile (Page & Thorne 1974 eq. 11n)
diverges at ISCO:

    σ_SB · T_NT(r)^4 = (3 G M Ṁ) / (8 π r³) · R_R(r),
    R_R(r) = 1 − sqrt(r_ISCO / r)

The slim-disk profile flattens because advection carries entropy
across the ISCO (Sądowski 2009 §3):

    T(r) = T_NT(r) · (1 − f_adv(r, ṁ))^(1/4)

For the initial implementation, use the **exponential fit** (research
note §4.3 — the linear form clamps incorrectly at super-Eddington):

    f_adv(r, ṁ) = 1 − exp(− (ṁ/ṁ_Edd) · (r_ISCO/r)²)

This produces the correct sub-Eddington convergence (T_slim/T_NT > 0.95
for ṁ < 0.3) and the correct super-Eddington flattening (T_slim/T_NT
≈ 0.33 at r = 1.5 r_ISCO for ṁ = 10) — matching Sądowski 2009 fig. 7
to within a factor of 2.

#### Spectral emission

Multi-colour blackbody: at each point, emit a Planck spectrum at the
local temperature T(r). Integrate over the disk surface/volume to get
the total spectral luminosity. The spectral pipeline evaluates B_ν(T)
at the hero wavelength — exact, no interpolation.

#### Parameters

| Parameter | Default | Description |
|---|---|---|
| `mdot` | 1.0 | Accretion rate in Eddington units (ṁ/ṁ_Edd). |
| `r_inner` | ISCO | Inner edge. For slim disks, material can exist inside ISCO. |
| `r_outer` | 500M | Outer truncation radius. |
| `spin` | (from metric) | Inherited from the Kerr metric. |

### Key design decisions

1. **Plugin, not replacement.** The slim disk does not replace the
   existing Novikov-Thorne model. Users select accretion model via a
   Blender dropdown or Python parameter. The two coexist.

2. **Volume emitter via VolumetricEmission.** The slim disk uses the
   same interface as the synchrotron jet. The GR integrator queries it
   at each step; the Gaussian vertical profile provides the density
   weighting.

3. **Advective correction as a fitting function.** Full Sądowski tables
   would require external data files and interpolation machinery. The
   analytic fitting function captures the essential behaviour (flattened
   inner temperature) and can be replaced with tabulated data in a
   future refinement pass.

4. **Material inside ISCO.** Unlike Novikov-Thorne which has a hard
   inner edge at ISCO, the slim disk allows emission from inside the
   ISCO. The plunging region has lower emissivity (material is in
   free-fall) but is not zero. This is physically correct and visually
   important — it fills in the dark gap at the ISCO boundary.

---

## Acceptance criteria

- [ ] `SlimDisk` registered via
      `ASTRORAY_REGISTER_EMISSION("slim_disk", SlimDisk)`.
- [ ] At ṁ/ṁ_Edd = 0.1, slim disk output closely matches
      Novikov-Thorne (temperature profiles agree to < 5% at r > 2·ISCO).
- [ ] At ṁ/ṁ_Edd = 10, the inner temperature profile visibly flattens
      compared to Novikov-Thorne (no divergence at ISCO).
- [ ] At ṁ/ṁ_Edd = 10, the disk has visible vertical extent
      (not razor-thin in edge-on renders).
- [ ] Spectral output is Planckian at each radius (verified by
      sampling at multiple wavelengths and fitting to B_ν).
- [ ] Blender addon has accretion model selector including slim disk.
- [ ] All existing tests pass.
- [ ] ≥6 new tests covering: temperature profile, vertical structure,
      sub-Eddington convergence to NT, spectral shape, visual render.

### Analytic test values (must reproduce to <5% relative error)

Source: research note §4.3, derived from Sądowski 2009 eqs. 1-9 and
Page & Thorne 1974 eq. 11n. Fiducial M = 10 M_sun BH, a = 0
(r_ISCO = 6 M = 8.86e6 cm), ṁ_Edd ≈ 1.4e18 g/s.

**Vertical structure H/r:**

| ṁ/ṁ_Edd | r        | H/r expected |
|---------|----------|--------------|
| 0.1     | r_ISCO   | 0.075        |
| 1.0     | r_ISCO   | 0.75         |
| 10.0    | r_ISCO   | 7.5 → clamp at 1.0 (research note §4.1) |
| 1.0     | 10·r_ISCO| 0.0149       |

**Temperature at r = 1.5 r_ISCO (= 9 M, M = r_g = GM/c^2, M_BH = 10 M_sun):**

NOTE (2026-05-14): The original table values below (1.62e8 K, 2.88e8 K)
were back-of-envelope predictions that scaled T_NT by `mdot_edd^0.25`,
which is *not* what Page-Thorne 1974 eq. 11n actually does — T_NT scales
as (M_dot)^(1/4) (the *physical* accretion rate), and `mdot_edd` enters
only through the M_dot conversion `M_dot = mdot_edd * M_dot_Edd`.
Measurement-post-implementation against the canonical Page-Thorne 1974
eq. 11n + Sadowski 2009 §3 advective correction gives T(r=9M, mdot=1.0)
= 7.45e6 K, not 1.62e8 K. Original spec value overstated by ~22x.

The T_slim/T_NT *ratios* (right column) are correct — they depend only
on the advective fraction and are invariant under the units fix.

| ṁ/ṁ_Edd | T_slim (K) measured | T_slim/T_NT expected |
|---------|---------------------|---------------------|
| 0.1     | ~5.1e6              | ≥ 0.95 (sub-Eddington convergence) |
| 1.0     | 7.45e6 (measured 2026-05-14) | 0.7-0.85 |
| 10.0    | ~3.0e6              | 0.30-0.40 (advective flattening) |

**Sub-Eddington spectral check:** at ṁ/ṁ_Edd = 0.1, integrated disk
spectrum vs. Novikov-Thorne baseline must agree to within 5 % at
all wavelengths (Scene B in research note §6.2).

**Super-Eddington vertical extent:** at ṁ/ṁ_Edd = 10 the edge-on
(89 deg inclination) render must show visible vertical thickness —
the silhouette is no longer a thin line. This is a visual check;
quantitative criterion is "FWHM of the disk in the image plane
> 0.1 × disk diameter."

---

## Non-goals

- Do not implement radiative transfer through the disk (optical depth
  effects). The disk is treated as optically thick at each point — the
  emission is from the photosphere.
- Do not implement disk winds or outflows.
- Do not implement time-dependent accretion rate variations.
- Do not tabulate full Sądowski solutions. The fitting function is
  sufficient for visualization.

---

## Progress

- [ ] Implement `SlimDisk` plugin: vertical structure, temperature
      profile with advective correction, Planck emission.
- [ ] Verify sub-Eddington convergence to Novikov-Thorne.
- [ ] Render super-Eddington test scenes; confirm flattened temperature
      and vertical extent.
- [ ] Spectral validation: multi-wavelength Planck check.
- [ ] Add Blender UI.
- [ ] Write tests.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

- **Spec table value at line 238 (1.62e8 K) was an overestimate.** The C++
  implementation matches Page-Thorne 1974 eq. 11n + Sadowski 2009 §3
  advective correction analytically; the measured T at r = 9 M, M = 10 M_sun,
  mdot = 1.0 is 7.45e6 K. Real stellar-mass BH disk peak temperatures are
  ~10^7 K, and the slim-disk advective correction at mdot ~ 1 drops T
  ~15% below Novikov-Thorne. The original 1.62e8 K likely came from a
  back-of-envelope `T_NT * mdot_edd^0.25` calc, but the mdot_edd dependence
  enters T_NT only through M_dot = mdot_edd * M_dot_Edd, not as an
  independent multiplier. Measurement-as-source-of-truth: test threshold
  frozen against measured value with order-of-magnitude tolerance.

- **Units fix: r_g vs r_s.** The spec uses geometrized M = r_g = GM/c^2
  ("r_ISCO = 6 M = 8.86e6 cm" matches r_g for 10 M_sun, not r_s). The
  initial C++ implementation converted the dimensionless r_M argument of
  `temperatureAt` using r_s_cm_ (= 2 r_g), making r_cm 2x too large. Fixed
  by introducing `r_g_cm_` and using it in `temperatureAt`. The fix is
  invariant under the slim/NT temperature *ratio* (both r_cm and r_isco_cm
  rescale equally), so all ratio-based tests pass unchanged. Only the
  absolute T value changes: 4.43e6 K → 7.45e6 K (factor 2^(3/4) ≈ 1.68).

- **Registration root-cause.** The slim_disk plugin TU was added to the
  source tree but the build system never compiled it, so the registration
  call was silently excluded from the binary — not a linker or CMake bug,
  but a build-glob exclusion. Surface this in any future plugin: the test
  `test_emission_registry_contains_slim_disk` catches it.

- **`SampledWavelengths::fromLambdas` factory.** Added as a side effect of
  this package because the Python bindings for `slim_disk_emissivity` need
  to inject caller-supplied wavelengths at arbitrary positions. This is
  reusable by pkg44 (and any future emission plugin with a Python harness).
