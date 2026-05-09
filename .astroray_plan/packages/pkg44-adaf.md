# pkg44 — ADAF Accretion Model

**Pillar:** 4
**Track:** B (plugin, self-contained)
**Status:** open
**Estimated effort:** 2 sessions (~5 h) — bumped from "1-2 sessions
(~4 h)" after research; the bremsstrahlung Gaunt factor and the
beta-convention mapping (research note §5.3) each warrant a unit test.
**Depends on:** pkg40 (Kerr metric), pkg42 (VolumetricEmission interface,
Pandya 2016 thermal j_nu/alpha_nu — pkg44 reuses pkg42's emissivity for
the synchrotron half)

**Reference research:** `.astroray_plan/docs/accretion-emission-research.md`
(ADAF profile §5, thermal synchrotron §2.2, transfer pipeline §1,
license matrix §7).

---

## Reference Implementations

The Narayan & Yi 1995 self-similar ADAF solution is a closed-form
power-law in r — no tabulated data needed. Numerical prefactors come
from Yuan & Narayan 2014 ARA&A §2.1 eqs. 8-16. Synchrotron emissivity
reuses the Pandya 2016 thermal Stokes-I fit from pkg42.

| Repo | Commit | License | Mirror permitted | Files to study |
|------|--------|---------|-----------------|----------------|
| (paper) Narayan & Yi 1995 ApJ 452, 710 | — | journal | math is public-domain; cite in code | original analytic solution |
| (paper) Yuan & Narayan 2014 ARA&A 52, 529 | — | journal | math is public-domain; cite eqs. 8-16 in code | numerical prefactors, wind exponent s |
| [ipole](https://github.com/AFD-Illinois/ipole) | `master` 2024-Q4 | BSD-3-Clause | Yes — radiation/transfer plumbing only | `src/radiation.c` (invariant transfer), `src/symphony/maxwell_juettner_fits.c` (pkg42 already mirrors this) |
| [RAPTOR](https://github.com/tbronzwaer/raptor) | `08cb9a2` | **GPLv3** | **No** — cross-validation only | Sgr A* / M87 ADAF cross-validation runs |
| [GYOTO](https://github.com/gyoto/Gyoto) | — | CeCILL | **No** — numerical cross-check only | `Astrobj/ThinDisk.C` with custom emissivity is the closest analogue |

Same fence as pkg40/pkg42: do **not** mirror RAPTOR even though it
implements both the Narayan-Yi profile and the Pandya 2016 fits. The
formulae are public domain; RAPTOR's C representation is GPLv3.

---

## Goal

**Before:** Astroray has thin-disk (Novikov-Thorne) and thick-disk
(slim disk, pkg43) accretion models. Neither handles the low-luminosity
regime where most supermassive black holes actually live — including
Sgr A* and M87*, the two targets of the Event Horizon Telescope.

**After:** An `ADAF` emission plugin implements a radiatively
inefficient accretion flow following Narayan & Yi 1994. The flow is
quasi-spherical, geometrically thick (H/r ~ 1), optically thin, and
two-temperature (T_ion ~ 10¹² K, T_e ~ 10⁹–10¹¹ K). Emission is
dominated by synchrotron and bremsstrahlung from the hot electrons.
This completes the accretion model trifecta: thin disk, slim disk,
ADAF — covering sub-Eddington, super-Eddington, and radiatively
inefficient regimes.

---

## Context

The ADAF is the accretion model most relevant to the Event Horizon
Telescope's primary targets. Sgr A* accretes at ~10⁻⁸ Eddington;
M87* at ~10⁻⁵ Eddington. At these rates, the gas is too hot and
tenuous to cool efficiently — almost all gravitational energy is
advected into the black hole rather than radiated. The resulting
quasi-spherical flow looks nothing like a thin disk; it fills the
volume around the black hole.

This is also the regime where the black hole shadow is most cleanly
visible, since the optically thin flow does not obscure the silhouette.

---

## Reference

- **Research notes (read first):** `.astroray_plan/docs/accretion-emission-research.md`
  (ADAF profile §5 — copy-paste prefactors and Sgr A* test values;
  pipeline §1; license matrix §7)
- Design doc: `.astroray_plan/docs/astrophysics.md §4.2`
- Narayan, R. & Yi, I. 1995, ApJ 452, 710 — self-similar ADAF solution
  (the original).
- Yuan, F. & Narayan, R. 2014, ARA&A 52, 529 — modern review with the
  outflow exponent s and numerical prefactors (eqs. 8-16; the formulae
  pkg44 implements verbatim).
- Broderick & Loeb 2006 — ADAF models applied to Sgr A* imaging.
- Karzas & Latter 1961 — Gaunt factor fitting formula for the
  bremsstrahlung emissivity.
- VolumetricEmission interface: `include/astroray/emission.h` (from pkg42)

---

## Prerequisites

- [ ] pkg40 is done: Kerr metric rendering working.
- [ ] pkg42 is done: `VolumetricEmission` interface exists.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/accretion/adaf.cpp` | `ADAF` emission plugin. |
| `tests/test_adaf.py` | Unit and integration tests. |
| `tests/scenes/adaf_sgra.py` | Test scene: Sgr A*-like ADAF around Kerr a=0.9, observer at 45° inclination. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Expose ADAF parameters. |
| `blender_addon/__init__.py` | Add ADAF to the accretion model selector dropdown. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg44 done. |
| `CHANGELOG.md` | Add pkg44 entry. |

### Physics model

#### Flow geometry (Yuan & Narayan 2014 eqs. 8-13)

Self-similar quasi-spherical flow. Use the Yuan & Narayan 2014 numerical
prefactors verbatim (research note §5.1, copy-paste form). With
m = M/M_sun, r in Schwarzschild radii R_S, ṁ_BH = inflow rate at the
hole in Eddington units, alpha = viscosity, s = outflow exponent:

    v_r(r)  = -1.1e10 · alpha · r^(-1/2)                              cm/s   (Y14 eq. 8)
    Omega(r)= 2.9e4   · m^(-1) · r^(-3/2)                              s^-1   (Y14 eq. 9)
    c_s²(r) = 1.4e20  · r^(-1)                                         cm²/s² (Y14 eq.10)
    n_e(r)  = 6.3e19  · alpha^(-1) · m^(-1) · ṁ_BH · r^(-3/2 + s)     cm^-3  (Y14 eq.11)
    B(r)    = 6.5e8   · (1+β_Y14)^(-1/2) · alpha^(-1/2)
                      · m^(-1/2) · ṁ_BH^(1/2) · r^(-5/4 + s/2)        G      (Y14 eq.12)

The wind/outflow generalization Mdot(r) = Mdot_BH (r/R_S)^s
(Y14 eq. 6) carries through the +s and +s/2 exponent corrections.
Numerical MHD simulations find s ≈ 0.3-0.5 (Y14 §3.2); pkg44 default
is s = 0.3.

The flow is geometrically thick (H/r ~ 1), modelled as a sphere with
no equatorial concentration (unlike the slim disk). Angular
distribution is uniform or weakly concentrated to the equatorial
plane depending on the `flattening` parameter (0 = spherical, 1 =
disk-like).

#### Two-temperature plasma (Yuan & Narayan 2014 eq. 16)

Ions follow virial (Y14 eq. 16):

    T_ion(r) ≈ G M m_p / (6 k_B R) ≈ (1.2e12 / r) K   // r in R_S

Electrons are cooler because Coulomb coupling from ions is inefficient
at low densities (Y14 §3.3):

    T_e(r) = T_e0 · (R_S / r)^q,    q = 1 (pkg44 fixed)

T_e0 ∈ [1e9, 1e11] K as the user parameter `electron_temp`; default
1e10 K for Sgr A*-like flows.

Only the electron temperature matters for emission — ions are too
heavy to radiate significantly.

**β-convention warning** (research note §5.3): the Y14 paper uses
β = p_gas / p_mag. The pkg44 user parameter `beta_mag` is the
inverse (p_mag / p_gas, the magnetisation). Map carefully in code:
`beta_Y14 = 1.0 / beta_mag`. A unit test must catch this inversion.

#### Emission mechanisms

Two contributions, both evaluated in the comoving frame:

1. **Thermal synchrotron** — use the Pandya 2016 Maxwell-Jüttner
   Stokes-I fit (eqs. 29, 31) with the local n_e, T_e, B, θ_B from
   §Flow geometry above. The exact copy-paste C++ form lives in
   research note §2.2 and is already implemented by pkg42's
   synchrotron module — pkg44 calls it directly, so the actual line
   count for synchrotron in pkg44 is one function call, not a
   re-implementation. (The qualitative form
   j_ν ∝ n_e · ν · exp(−ν/ν_c) is recovered in the high-X limit.)
   Magnetic field B is from Y14 eq. 12 above, not from a separate
   pressure-balance assumption.

2. **Thermal bremsstrahlung** (free-free):

       j_ν^ff ∝ n_e² · T_e^(-1/2) · exp(−hν / k_B T_e) · g_ff(ν, T_e)

   where g_ff is the velocity-averaged Gaunt factor (use the Karzas &
   Latter 1961 fitting formula; ~5 lines).

Total emissivity: j_ν = j_ν^sync + j_ν^ff. In practice, synchrotron
dominates at radio/mm wavelengths and bremsstrahlung at X-ray.

#### Radiative transfer

Optically thin: no self-absorption for the initial implementation.
The ray accumulates j_ν · ds along its path through the flow. Doppler
boosting from the orbital velocity of the flow uses the same D³
machinery as the synchrotron jet (pkg42).

#### Parameters

| Parameter | Default | Description |
|---|---|---|
| `mdot_edd` | 1e-5 | Accretion rate in Eddington units. |
| `electron_temp` | 5e10 | Electron temperature at outer boundary (K). |
| `beta_mag` | 0.1 | Magnetic pressure fraction (B²/8π / P_gas). |
| `r_inner` | horizon | Inner boundary (default: just outside horizon). |
| `r_outer` | 100M | Outer boundary of the ADAF. |
| `flattening` | 0.0 | Angular concentration (0 = spherical, 1 = equatorial). |
| `spin` | (from metric) | Inherited from Kerr metric. |

### Key design decisions

1. **Self-similar solution, not numerical.** Full ADAF solutions
   require solving coupled ODEs (Narayan & Yi 1994 §3). The self-similar
   power-law profiles are the standard approximation for visualization
   and are used by GYOTO and similar tools. Sufficient for Astroray's
   "outreach and rough predictions" scope.

2. **Two emission mechanisms, not three.** Inverse Compton scattering
   (Comptonisation) is important for X-ray spectra but requires
   iterative radiative transfer. Excluded for the initial plugin;
   can be added as an enhancement without changing the interface.

3. **Comoving-frame emission + Doppler boost.** Same pattern as the
   synchrotron jet: compute emissivity in the plasma rest frame, apply
   D³ from the bulk orbital velocity. The orbital velocity is
   sub-relativistic for the ADAF (unlike the jet), so the Doppler
   effect is modest but still physically correct.

4. **Gaunt factor as fitting formula.** The exact quantum-mechanical
   Gaunt factor is a 2D function of frequency and temperature. The
   Born approximation fitting formula from Karzas & Latter is standard
   and accurate to ~10% across the relevant parameter space.

---

## Acceptance criteria

- [ ] `ADAF` registered via
      `ASTRORAY_REGISTER_EMISSION("adaf", ADAF)`.
- [ ] Test scene produces a quasi-spherical glow around the black hole
      (not a disk shape) with the shadow visible as a dark silhouette.
- [ ] At ṁ/ṁ_Edd = 10⁻⁵ (Sgr A*-like), the total luminosity is
      << Eddington (visually much dimmer than a thin-disk render at the
      same camera settings).
- [ ] Spectral test: emission spectrum shows synchrotron peak at
      sub-mm / infrared wavelengths and bremsstrahlung contribution at
      shorter wavelengths, consistent with the two-temperature model.
- [ ] Density and temperature profiles follow the self-similar scaling:
      ρ ∝ r^(-3/2+s), T_e ∝ r^(-1) (verified by sampling at multiple
      radii in the test).
- [ ] Blender addon includes ADAF in accretion model selector.
- [ ] All existing tests pass.
- [ ] ≥6 new tests covering: density profile, temperature profile,
      synchrotron emissivity, bremsstrahlung emissivity, shadow
      visibility, spectral shape.

### Analytic test values (must reproduce within stated tolerance)

Source: research note §5.4, derived from Yuan & Narayan 2014
eqs. 8-16. Sgr A*-like fiducial: M = 4.0e6 M_sun (m = 4e6),
ṁ_BH = 1e-8, alpha = 0.1, beta_mag = 0.1 (so β_Y14 = 10),
s = 0.3, T_e0 = 1e10 K, q = 1.

**Profiles at r = 10 R_S** (50 % tolerance — Y14 prefactors are
themselves order-unity uncertain):

| Quantity | Expected | Tolerance |
|----------|----------|-----------|
| n_e      | ~10 cm⁻³ | ±50 %     |
| B        | ~2.5e-5 G | ±50 %    |
| T_ion    | 1.2e11 K  | ±5 %     |
| T_e      | 1e9 K     | ±5 %     |

**Profiles at r = 2 R_S:**

| Quantity | Expected | Tolerance |
|----------|----------|-----------|
| n_e      | ~6.9e4 cm⁻³ | ±50 %  |
| B        | ~1.45e-4 G  | ±50 %  |
| T_ion    | 6e11 K      | ±5 %   |
| T_e      | 5e9 K       | ±5 %   |

**Density power-law exponent:** log(n_e(r1)/n_e(r2)) / log(r1/r2)
must equal -(3/2 - s) = -1.2 (for s = 0.3) to within 1e-3.

**Temperature power-law exponent:** log(T_ion(r1)/T_ion(r2)) /
log(r1/r2) must equal -1.0 to within 1e-3.

**β-convention regression:** at beta_mag = 0.1, the computed B must
match the Y14 eq. 12 numerical prefactor with (1 + 10)^(-1/2)
= 0.302, NOT (1 + 0.1)^(-1/2) = 0.953. (Catches the inversion bug
the research note §5.3 warns about.)

**Sgr A* image-plane sanity (Scene C in research note §6.3):**
total flux at 230 GHz must be order ~3 Jy (Sgr A* observed) to
within a factor of 3. Coarser tolerance because the result depends
on the integration volume cutoff and inclination.

---

## Non-goals

- Do not implement Comptonisation / inverse Compton scattering.
- Do not implement convection-dominated accretion flows (CDAFs).
- Do not implement jet launching from the ADAF (jets are pkg42).
- Do not solve the full ADAF ODEs numerically. Self-similar profiles
  are sufficient.
- Do not implement polarised radiative transfer.

---

## Progress

- [ ] Implement density and temperature profiles.
- [ ] Implement thermal synchrotron emissivity.
- [ ] Implement thermal bremsstrahlung with Gaunt factor.
- [ ] Wire as VolumetricEmission plugin.
- [ ] Create Sgr A*-like test scene.
- [ ] Verify shadow visibility in renders.
- [ ] Spectral validation.
- [ ] Add Blender UI.
- [ ] Write tests.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*
