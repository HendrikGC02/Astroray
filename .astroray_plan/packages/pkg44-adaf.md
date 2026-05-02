# pkg44 — ADAF Accretion Model

**Pillar:** 4
**Track:** B (plugin, self-contained)
**Status:** open
**Estimated effort:** 1–2 sessions (~4 h)
**Depends on:** pkg40 (Kerr metric), pkg42 (VolumetricEmission interface)

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

- Design doc: `.astroray_plan/docs/astrophysics.md §4.2`
- Narayan & Yi 1994 — self-similar ADAF solution
- Yuan & Narayan 2014 — review of hot accretion flows
- Broderick & Loeb 2006 — ADAF models for Sgr A* imaging
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

#### Flow geometry

Self-similar quasi-spherical flow. Density profile:

    ρ(r) = ρ₀ · (r / r_out)^(-3/2 + s)

where s ≈ 0.3 is the self-similar index from Narayan & Yi (1994).
The flow is geometrically thick: H/r ~ 1, modelled as a sphere with
no equatorial concentration (unlike the slim disk). Angular
distribution is uniform or weakly concentrated to the equatorial
plane depending on the `flattening` parameter (0 = spherical, 1 =
disk-like).

#### Two-temperature plasma

Ions and electrons are not in thermal equilibrium:

    T_ion(r) = T_vir(r) = (G M m_p) / (3 k_B r) ≈ 10¹² K · (M/r)
    T_e(r) = T_e0 · (r / r_out)^(-1)

with T_e0 ~ 10⁹–10¹¹ K as a user parameter. The ion temperature
follows the virial temperature; the electron temperature is lower
because Coulomb coupling is inefficient at low densities.

Only the electron temperature matters for emission — ions are too
heavy to radiate significantly.

#### Emission mechanisms

Two contributions, both evaluated in the comoving frame:

1. **Thermal synchrotron** from hot electrons in the magnetised
   accretion flow:

       j_ν^sync ∝ n_e · ν · exp(−ν / ν_c)

   where ν_c ∝ T_e² B is the critical frequency. The magnetic field
   is parameterised as a fraction β_mag of the gas pressure:
   B² / 8π = β_mag · ρ k_B T_ion / m_p.

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
