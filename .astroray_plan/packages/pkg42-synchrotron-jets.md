# pkg42 — Synchrotron Emission & Relativistic Jets

**Pillar:** 4  
**Track:** B (plugin, self-contained) with Track A review  
**Status:** done (PR #245, 2026-05-11 — second post-gate Pillar-4 deliverable)
**Estimated effort:** 2 sessions (~6 h) — unchanged after research; the
fitting formulae are short and Codex-paste-ready.
**Depends on:** pkg40 (Kerr metric), pkg14 (spectral pipeline), EmissionRegistry scaffold

**Reference research:** `.astroray_plan/docs/accretion-emission-research.md`
(pipeline overview §1, j_nu fits §2, alpha_nu §3, license matrix §7 — read
this before writing any emission code).

---

## Reference Implementations

All synchrotron formulae are from Pandya, Zhang, Chandra & Gammie 2016,
ApJ 822, 34 (DOI 10.3847/0004-637X/822/1/34; arXiv:1602.08749), Appendix A,
eqs. 29-34. The repos below are code-shape references; the math itself is
the paper.

| Repo | Commit | License | Mirror permitted | Files to study |
|------|--------|---------|-----------------|----------------|
| [ipole](https://github.com/AFD-Illinois/ipole) (Mościbrodzka & Gammie 2018, MNRAS 475 43) | `master` 2024-Q4 (pin SHA at first use) | BSD-3-Clause | Yes — cite file + commit in code | `src/symphony/maxwell_juettner_fits.c` (Pandya eqs. 29, 31), `src/symphony/power_law_fits.c` (eqs. 29, 33), `src/radiation.c` (invariant transfer plumbing) |
| [RAPTOR](https://github.com/tbronzwaer/raptor) (Bronzwaer et al. 2018, A&A 613 A2) | `08cb9a2` | **GPLv3** | **No** — cross-validation only | `model.c` / `radiative_transfer.c` (do **not** read for code shape) |
| [symphony standalone](https://github.com/AFD-Illinois/symphony) | — | **GPLv3** | **No** — use the ipole-vendored BSD-3 copy instead | — |
| [GYOTO](https://github.com/gyoto/Gyoto) | — | CeCILL (GPL-incompat) | **No** — numerical cross-check only | — |

**Do not mirror RAPTOR or standalone-symphony code** even though their
implementations of the Pandya 2016 fits would be convenient. GPLv3 is
incompatible with Astroray's license. The math is in the public domain;
RAPTOR's C representation of it is not what we borrow. (Same fence as
pkg40 / pkg67.) The ipole-vendored copy of symphony is BSD-3 and is the
correct source.

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

- **Research notes (read first):** `.astroray_plan/docs/accretion-emission-research.md`
  (pipeline §1, j_nu §2, alpha_nu §3, license matrix §7)
- Design doc: `.astroray_plan/docs/astrophysics.md §4.3`
- Pandya, Zhang, Chandra & Gammie 2016, ApJ 822, 34 — synchrotron
  fitting formulae, eqs. 29-34 (the math we implement)
- Pandya et al. 2018, ApJ 868, 13 — polarised extension (deferred,
  see Non-goals)
- Rybicki & Lightman 1979 ch. 6 — synchrotron theory background
  (cite-only, do not copy text)
- Blandford & Königl 1979 — conical jet geometry rationale
- Spectral pipeline: `include/astroray/spectrum.h` (SampledSpectrum)
- GR integrator: `include/astroray/gr_metric.h` (from pkg40)
- Emission plugin registry: `include/astroray/register.h`
- Cross-check tools: ipole (BSD-3 — selective mirror permitted),
  RAPTOR (GPLv3 — cross-validation only), GYOTO (CeCILL — reference
  only)

---

## Prerequisites

- [x] pkg40 is done: Kerr metric tensors and analytic quantities are available.
- [x] `EmissionRegistry` and `ASTRORAY_REGISTER_EMISSION` exist in
      `include/astroray/register.h`.
- [x] Spectral pipeline (Pillar 2) is complete.
- [x] Build passes on main.
- [x] Focused pkg42 tests pass.

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

#### Synchrotron emissivity (Pandya 2016, eqs. 29 & 33)

Power-law electron energy distribution: dN/dγ ∝ γ^(-p) for
γ ∈ [γ_min, γ_max], p = 2.5 (default; user-configurable). Use the
Pandya 2016 power-law Stokes-I fit verbatim — see
`accretion-emission-research.md §2.3` for the copy-paste C++ form.
The spectral slope is -(p-1)/2 = -0.75 for p = 2.5 (canonical AGN
jet slope).

Validity envelope (Pandya 2016 §3.2): γ_min² < ν / ν_c < γ_max²,
p ∈ [1.5, 6.5]. Outside that band the fit is no longer the physical
emissivity; this is a fundamental limit, not a code bug.

#### Synchrotron absorptivity (Pandya 2016, eq. 33)

α_ν^I formula in `accretion-emission-research.md §3.2`. Defaults to
`include_self_absorption = false` because for p = 2.5 the absorption
slope is ν^(-3.25) from the full eq. 33 prefactor; above ~GHz the medium
is optically thin. The
toggle exists for completeness.

#### Bulk relativistic motion → invariant radiative transfer

The bulk Lorentz factor γ_jet enters the transfer through the *fluid
rest-frame frequency* ν_fluid, not through a separate D³ multiplier.
The geodesic integrator already supplies the photon 4-momentum k^μ
at every step; the jet plasma 4-velocity u^μ is analytic (radial
outflow at γ_jet along the cone). Then:

    ν_fluid = -k_μ u^μ / h
    j_inv   = j_ν(ν_fluid, ...) / ν_fluid^2
    α_inv   = α_ν(ν_fluid, ...) * ν_fluid

and the integrator advances I_inv = I_ν / ν^3 along the affine
parameter:

    dI_inv / dλ = j_inv − α_inv · I_inv

At the camera, recover I_observed = I_inv · ν_obs^3. The factor of
ν^3 redshift handles bulk Doppler boosting *and* gravitational
redshift in one place. **Do not also multiply by D³** — that
double-counts the redshift. (See `accretion-emission-research.md §1`
for the derivation; same pattern as ipole, Mościbrodzka & Gammie
2018 §2.4, BSD-3.)

For γ_jet = 10 and head-on viewing the invariant formulation
recovers the colloquial D³ ≈ 8000 brightness boost on the
approaching jet automatically; the regression test in the
Acceptance section verifies this.

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

3. **Invariant transfer, not explicit D³.** The fluid-frame frequency
   ν_fluid = −k_μ u^μ_jet / h is computed from the geodesic state at
   each step. j_ν and α_ν are evaluated at ν_fluid, converted to
   invariant form (j/ν², α·ν), and integrated as I_inv = I/ν³ along
   the affine parameter. At the camera I_obs = I_inv · ν_obs³. This
   is what ipole and RAPTOR both do. The colloquial D³ boost emerges
   automatically from the ν³ factor. See research note §1.

4. **No GR corrections to the emissivity itself.** Emissivity is
   computed in the fluid rest frame; the invariant transfer handles
   *both* bulk Doppler and gravitational redshift in one ν³ factor.
   Do not apply any extra Doppler or redshift multipliers.

5. **Spectral pipeline integration.** The synchrotron spectrum is a
   power law: j_ν ∝ ν^α where α = -(p-1)/2. Evaluating at the hero
   wavelength is exact for a power law — no interpolation artifacts.
   The `SampledSpectrum` return type plugs directly into the spectral
   path tracer's accumulator.

---

## Acceptance criteria

- [x] `SynchrotronJet` plugin registered via
      `ASTRORAY_REGISTER_EMISSION("synchrotron_jet", SynchrotronJet)`.
- [x] `VolumetricEmission` base class exists in
      `include/astroray/emission.h`.
- [x] Test scene renders a black-hole influence sphere with bipolar jets at
      45° inclination. Visual inspection/smoke coverage confirms:
      - Approaching jet is dramatically brighter than receding jet.
      - Jets emerge along the spin axis.
      - Jet brightness falls off with distance from the BH.
- [x] Quantitative Doppler test: for γ=10, the peak brightness ratio
      between approaching and receding jets is within 20% of the
      analytic D³ prediction (~8000× for head-on viewing).
- [x] Spectral test: the output spectrum of the jet follows a power
      law ν^(-(p-1)/2) to within 5% over the visible range.
- [x] Blender addon exposes jet parameters (Lorentz factor, half-angle,
      power-law index, density, magnetic field).
- [x] Focused pkg40/pkg41/pkg42 tests pass.
- [x] ≥8 new tests covering: emissivity calculation, fluid-frame
      frequency / invariant transfer, jet geometry (inside/outside
      cone), spectral slope, visual render.

### Analytic test values (must reproduce to <1e-6 relative error)

Source: Pandya 2016 §A1 + research note §2. Full derivation in
`accretion-emission-research.md §2-§3`.

**Thermal Stokes-I at X = 1, θ_B = π/2:**

```
J_S(X=1, θ_B=π/2)
  = (sqrt(2)·π/27) · 1 · (1 + 2^(11/12))² · exp(-1)
  ≈ 0.5023
j_ν^I(X=1) = 0.5023 · n_e · e² · ν_c / c
```

For B = 1 G, n_e = 1 cm⁻³ → j_ν^I ≈ 1.083e-23 erg/(s·cm³·Hz·sr).

**Power-law spectral slope:** for p = 2.5, log(j_ν1/j_ν2)/log(ν1/ν2)
must equal −0.75 to within 1e-3 over ν ∈ [10 ν_c, 100 ν_c].

**Optically-thin sphere check (Scene A in research note §6.1):**
flat space, sphere radius 100 cm, n_e = 1 cm⁻³, T_e = 1e10 K, B = 1 G.
Through-center pixel intensity at 1 GHz must equal
j_ν^I(thermal) · 200 cm to within 1e-3 (no GR, no self-absorption,
analytic upper bound).

**Bulk-boost check:** for γ_jet = 10, head-on viewing (θ_obs ≈ 0),
peak intensity ratio I_approach / I_recede must equal D³ ≈ 8000 to
within 20 %. (This is the invariant ν³ working out in practice.)

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

- [x] Define `VolumetricEmission` interface in
      `include/astroray/emission.h`.
- [x] Add `EmissionRegistry` to `register.h`.
- [x] Implement `SynchrotronJet` plugin: geometry, density/B-field
      profiles, emissivity, Doppler factor.
- [x] Wire `BlackHole` integration loop to query emission plugins.
- [x] Write test scene (`synchrotron_jet.py`).
- [x] Unit tests: emissivity, Doppler factor, geometry.
- [x] Integration test: render smoke plus analytic brightness ratio.
- [x] Spectral test: verify power-law slope.
- [x] Add Blender UI parameters.
- [x] Focused test suite green.
- [x] Update STATUS.md, CHANGELOG.md.

---

## Lessons

- pkg42 implements the emission interface and jet plugin now, but full Kerr
  invariant geodesic transfer remains pkg67 scope because
  `KerrMetric::geodesic_rhs` is still intentionally reserved. The current
  black-hole integration consumes the plugin through the existing
  Schwarzschild GR influence sphere and a local optically-thin segment
  fallback; the plugin API is shaped so pkg67 can replace that with
  `j_nu / nu^2` invariant transfer without changing the emitter.
- The Pandya 2016 power-law absorptivity slope in the package text was
  corrected from `nu^-2.25` to `nu^-3.25` for p=2.5: eq. 33's term4
  contributes `nu^(-(p+2)/2)` and the prefactor contributes another `nu^-1`.
- Verification on 2026-05-10:
  `scripts\build\build_cuda.bat` completed, and
  `python scripts\dev\run_tests.py --build-dir build_cuda -- tests/test_synchrotron.py -v --tb=short`
  collected 9 tests and passed all 9.
