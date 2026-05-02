# pkg42 — Synchrotron Emission & Relativistic Jets

**Pillar:** 4  
**Track:** B (plugin, self-contained) with Track A review  
**Status:** open  
**Estimated effort:** 2 sessions (~6 h)  
**Depends on:** pkg40 (Kerr metric), pkg14 (spectral pipeline)

---

## Goal

**Before:** Astroray can render black holes with a thin accretion disk
(Novikov-Thorne) but has no volumetric emission model. Jets — the most
visually spectacular feature of accreting black holes — cannot be
rendered.

**After:** A `SynchrotronJet` emission plugin renders a pair of
relativistic jets along the black hole spin axis. The plugin computes
spectral synchrotron emissivity from a power-law electron distribution,
applies relativistic Doppler boosting (D³ beaming), and produces the
characteristic extreme brightness asymmetry between the approaching and
receding jets. The result integrates naturally with the spectral pipeline
and the GR geodesic integrator.

---

## Context

Synchrotron jets are the single most dramatic visual effect Astroray
can produce. For a Lorentz factor γ = 10, the approaching jet is
~10⁵× brighter than the counter-jet due to relativistic beaming.
Combined with Kerr frame-dragging and a spectrally-resolved pipeline,
this is Astroray's strongest showcase for astrophysical visualization.

The synchrotron emission model is well-understood and analytically
tractable — no numerical tables or external preprocessing required.
This makes it a clean self-contained plugin.

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.3`
- Rybicki & Lightman 1979 — "Radiative Processes in Astrophysics"
  ch. 6 (synchrotron theory)
- Pacholczyk 1970 — synchrotron spectral functions F(x), tabulated
- Blandford & Königl 1979 — jet model (conical geometry + power-law
  density profile)
- Spectral pipeline: `include/astroray/spectrum.h` (SampledSpectrum)
- GR integrator: `include/astroray/gr_metric.h` (from pkg40)

---

## Prerequisites

- [ ] pkg40 is done: Kerr metric renders working.
- [ ] Spectral pipeline (Pillar 2) is complete.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/emission/synchrotron.cpp` | `SynchrotronJet` emission plugin. Computes spectral emissivity along ray segments through the jet volume. |
| `include/astroray/emission.h` | `VolumetricEmission` abstract base class — the interface all volumetric emission plugins implement. |
| `tests/test_synchrotron.py` | Unit and integration tests. |
| `tests/scenes/synchrotron_jet.py` | Test scene: Kerr a=0.9 BH with bipolar jets, observer at 45° inclination. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/register.h` | Add `EmissionRegistry` typedef and `ASTRORAY_REGISTER_EMISSION` macro. |
| `plugins/shapes/black_hole.cpp` | During GR ray integration, query registered emission plugins for volumetric contribution along each ray segment. Accumulate spectral radiance using emission-absorption radiative transfer (no scattering). |
| `module/blender_module.cpp` | Expose jet parameters: `jet_lorentz_factor`, `jet_half_angle`, `jet_power_law_index`, `jet_base_density`, `jet_magnetic_field`. |
| `blender_addon/__init__.py` | Add jet parameter UI to the black hole panel. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg42 done; update Pillar 4 percentage. |
| `CHANGELOG.md` | Add pkg42 entry. |

### Physics model

#### Jet geometry

Conical bipolar jets along the spin axis (z-axis in BL coordinates).
Parameterised by:

- `half_angle` (default 5°) — opening half-angle of the cone.
- `r_base` (default 6M) — inner radius where jets start (≈ ISCO).
- `r_max` (default 500M) — outer truncation radius.
- `lorentz_factor` γ (default 5) — bulk Lorentz factor of the jet
  plasma. Velocity β = √(1 − 1/γ²), directed radially outward along
  the cone.

Density profile: n(r) = n₀ (r/r_base)^(-2) (conical expansion
conserves particle flux).

Magnetic field profile: B(r) = B₀ (r/r_base)^(-1) (toroidal field
decays as 1/r in a conical jet).

#### Synchrotron emissivity

Power-law electron energy distribution: N(E) ∝ E^(-p), p = 2.5
(default; user-configurable).

Spectral emissivity per unit volume:

    j_ν = C(p) · n₀ · B^((p+1)/2) · ν^(-(p-1)/2)

where C(p) is the standard synchrotron constant from Rybicki &
Lightman eq. 6.36. This gives a power-law spectrum j_ν ∝ ν^(-0.75)
for p=2.5.

For the spectral pipeline: evaluate j_ν at the hero wavelength
λ = c/ν and return a `SampledSpectrum`. The power-law form means no
tabulated data is needed.

#### Relativistic Doppler boosting

The observed specific intensity transforms as:

    I_ν(obs) = D³ · I'_ν'(comoving)

where D = 1 / (γ(1 − β cos θ_obs)) is the Doppler factor and
θ_obs is the angle between the jet velocity and the photon direction
in the observer frame.

For γ = 10 and θ_obs ≈ 0 (approaching): D ≈ 20, boost ≈ 8000.  
For θ_obs ≈ π (receding): D ≈ 1/20, suppression ≈ 1/8000.

The D³ factor applies because synchrotron emission is optically thin
and we are boosting specific intensity (not flux). This is the
standard result for a moving optically-thin emitter.

#### Radiative transfer along ray

For each ray segment through the jet volume:

    dI_ν/ds = j_ν(s) − α_ν(s) · I_ν(s)

where α_ν is the synchrotron self-absorption coefficient. For the
jets in most AGN/XRB scenarios, self-absorption is negligible above
~GHz frequencies. The plugin computes it but defaults to optically
thin (α_ν ≈ 0) for the initial implementation. A user parameter
`include_self_absorption` (default false) enables the full transfer.

Accumulation: step along the ray in the GR integrator, evaluate j_ν
at each step, multiply by D³, and add to the running spectral
radiance.

### Key design decisions

1. **VolumetricEmission interface.** All volumetric emitters (jets,
   ADAF, HII regions) implement the same interface:
   ```
   virtual SampledSpectrum emissivity(
       const Vec3d& position,
       const Vec3d& photon_direction,
       const SampledWavelengths& lambdas) const = 0;
   ```
   This keeps the GR integration loop generic. The `BlackHole` shape
   iterates over registered emission plugins at each integration step.

2. **Jet lives in the metric's coordinate system.** The jet cone axis
   is the spin axis. Jet geometry is evaluated in Boyer-Lindquist
   coordinates directly — no coordinate transform needed since the
   GR integrator already works in BL.

3. **Doppler factor computed from the geodesic.** The photon 4-momentum
   is available at each integration step (it is the `GeodesicState`
   momenta). The jet plasma 4-velocity is known analytically (radial
   outflow at γ along the cone). The Doppler factor is the ratio of
   photon energies in the two frames:
   D = −(p_μ u^μ_obs) / (p_μ u^μ_jet).

4. **No GR corrections to the emissivity itself.** The emissivity is
   computed in the comoving frame; the D³ factor handles the frame
   transformation. Gravitational redshift is already handled by the
   geodesic integrator (the photon frequency at the observer is the
   correct one). Do not apply redshift twice.

5. **Spectral pipeline integration.** The synchrotron spectrum is a
   power law: j_ν ∝ ν^α where α = -(p-1)/2. Evaluating at the hero
   wavelength is exact for a power law — no interpolation artifacts.
   The `SampledSpectrum` return type plugs directly into the spectral
   path tracer's accumulator.

---

## Acceptance criteria

- [ ] `SynchrotronJet` plugin registered via
      `ASTRORAY_REGISTER_EMISSION("synchrotron_jet", SynchrotronJet)`.
- [ ] `VolumetricEmission` base class exists in
      `include/astroray/emission.h`.
- [ ] Test scene renders a Kerr a=0.9 BH with bipolar jets at 45°
      inclination. Visual inspection confirms:
      - Approaching jet is dramatically brighter than receding jet.
      - Jets emerge along the spin axis.
      - Jet brightness falls off with distance from the BH.
- [ ] Quantitative Doppler test: for γ=10, the peak brightness ratio
      between approaching and receding jets is within 20% of the
      analytic D³ prediction (~8000× for head-on viewing).
- [ ] Spectral test: the output spectrum of the jet follows a power
      law ν^(-(p-1)/2) to within 5% over the visible range.
- [ ] Blender addon exposes jet parameters (Lorentz factor, half-angle,
      power-law index, density, magnetic field).
- [ ] All existing tests pass.
- [ ] ≥8 new tests covering: emissivity calculation, Doppler factor,
      jet geometry (inside/outside cone), spectral slope, visual render.

---

## Non-goals

- Do not implement jet precession or time-variable jets.
- Do not implement polarisation (Stokes parameters). That is a future
  physical optics package.
- Do not implement synchrotron self-Compton (SSC). The plugin is
  optically-thin synchrotron only.
- Do not implement jets from non-black-hole sources (pulsars, YSOs).
  The plugin is coupled to the GR integrator.
- Do not worry about performance for this package. The jet volume is
  small and the emissivity is cheap (one power-law evaluation per
  step). Optimisation is premature.

---

## Progress

- [ ] Define `VolumetricEmission` interface in
      `include/astroray/emission.h`.
- [ ] Add `EmissionRegistry` to `register.h`.
- [ ] Implement `SynchrotronJet` plugin: geometry, density/B-field
      profiles, emissivity, Doppler factor.
- [ ] Wire `BlackHole` integration loop to query emission plugins.
- [ ] Write test scene (`synchrotron_jet.py`).
- [ ] Unit tests: emissivity, Doppler factor, geometry.
- [ ] Integration test: render and check brightness ratio.
- [ ] Spectral test: verify power-law slope.
- [ ] Add Blender UI parameters.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*
