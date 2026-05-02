# pkg43 — Slim Disk Accretion Model

**Pillar:** 4
**Track:** B (plugin, self-contained)
**Status:** open
**Estimated effort:** 1–2 sessions (~4 h)
**Depends on:** pkg40 (Kerr metric), pkg42 (VolumetricEmission interface)

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

- Design doc: `.astroray_plan/docs/astrophysics.md §4.2`
- Abramowicz et al. 1988 — slim disk formulation
- Sądowski 2009 — numerical slim disk solutions, tables
- Existing Novikov-Thorne: current accretion disk code in
  `black_hole.cpp` or GR renderer
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

#### Vertical structure

Unlike the razor-thin Novikov-Thorne disk, the slim disk has a
half-thickness H(r) that depends on accretion rate:

    H/r ≈ (3/2) · (ṁ / ṁ_Edd) · f(r)

where f(r) encodes the radial dependence from Sądowski (2009). At
sub-Eddington rates H/r << 1 and the model reduces to Novikov-Thorne.
At super-Eddington rates (ṁ/ṁ_Edd > 1) the inner disk can reach
H/r ~ 0.5, making it a genuine volume emitter.

The plugin implements the disk as a volume with density concentrated
in the equatorial region: ρ(r,θ) ∝ exp(−z²/2H²) where z = r cos θ.

#### Temperature profile

The Novikov-Thorne temperature profile diverges at the ISCO. The slim
disk profile flattens because advection carries entropy across the
ISCO:

    T(r) = T_NT(r) · [1 − f_adv(r, ṁ)]^(1/4)

where f_adv is the advective fraction from Sądowski (2009) Table 2
(tabulated for a grid of spin and ṁ values). For the initial
implementation, use a fitting function rather than a full table:

    f_adv(r) ≈ (ṁ/ṁ_Edd) · (r_ISCO/r)^2 · [1 + (r/r_ISCO)^2]^(-1)

This captures the essential physics: advection dominates near and
inside the ISCO, and is negligible at large radii.

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

*(Fill in after the package is done.)*
