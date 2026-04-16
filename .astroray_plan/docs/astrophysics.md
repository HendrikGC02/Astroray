# Pillar 4: Astrophysics Platform

**Status:** Not started
**Depends on:** Pillars 1, 2
**Track:** A (Kerr core), B (phenomena as plugins)
**Duration:** 6–10 weeks, parallel with other pillars

## Goal

Turn Astroray into a real astrophysical visualization platform, not a
renderer that happens to have a black hole. Every phenomenon is a
plugin — users enable only what they need.

## Coverage

- GR metrics: Kerr in addition to existing Schwarzschild.
- Accretion flows: slim disk, ADAF (in addition to existing Novikov-Thorne).
- Synchrotron jets with relativistic Doppler boost.
- HII region emission-line spectroscopy (Hα, Hβ, [OIII], [NII]).
- Simulation data import: FITS, HDF5/yt, SPH.
- Weak gravitational lensing (screen-space).
- Synthetic telescope observations: wavelength-dependent PSF + noise.

## References and tools

- **GYOTO** https://github.com/gyoto/Gyoto — CPU GR ray tracer. GPL-3
  so we cannot link; used as numerical cross-check only.
- **GRay2** https://github.com/luxsrc/GRay2 — GPU GR ray tracer
  (Cartesian Kerr-Schild). GPL-3, same constraint.
- **yt** https://yt-project.org/ — Python scientific viz. BSD. Used as
  preprocessing; no C++ dep.
- **CLOUDY** https://www.nublado.org/ — photoionization code. GPL; run
  as preprocessing tool to generate emissivity tables.
- **CFITSIO** — FITS I/O, permissive license.
- **EleFits** — modern C++20 FITS wrapper (LGPL-3, dynamic link OK).
- **HighFive** — header-only HDF5 wrapper, BSD-3.
- **WebbPSF/STPSF** — PSF simulation, BSD. Python preprocessing.

Key papers:
- Novikov-Thorne 1973 (done), Narayan & Yi 1994 (ADAF),
  Sądowski 2009 (slim disk), Cárdenas-Avendaño 2022 (photon ring
  analytic), Eggleton 1983 (Roche lobe).

## Design

### 4.1 Kerr geodesic integration

Existing `GRIntegrator` becomes a plugin with:
- `SchwarzschildIntegrator` (a=0 case; existing validated code
  lightly refactored)
- `KerrIntegrator` (new, Hamiltonian formulation in Boyer-Lindquist)

```cpp
class GRMetric {
public:
    virtual ~GRMetric() = default;
    virtual void derivatives(const GeodesicState&, GeodesicState&) const = 0;
    virtual bool horizonCrossed(const GeodesicState&) const = 0;
};

ASTRORAY_REGISTER_METRIC("schwarzschild", SchwarzschildMetric)
ASTRORAY_REGISTER_METRIC("kerr", KerrMetric)
```

Dormand-Prince RK4/5 + adaptive stepping + conservation monitoring
(E, L_z, Carter constant Q). Step size ∝ Δ(r) near horizon. Use the
**r < 2.5M** capture threshold from the validated Python implementation
— this is a hard-won lesson and must not drift.

Double precision for the integrator, float elsewhere (per the
research report; GRay and EinsteinPy both document numerical
difficulties in FP32 near coordinate singularities). BL coords first;
consider Kerr-Schild if BL isn't fast enough on GPU.

Packages: `pkg30-kerr-metric.md`, `pkg31-kerr-tests.md`.

### 4.2 Accretion models beyond thin disk

Plugins:
- `plugins/accretion/slim_disk.cpp` — super-Eddington, advection
  matters, temperature profile flattens.
- `plugins/accretion/adaf.cpp` — low accretion, nearly spherical,
  two-temperature (T_ion ~ 10¹² K, T_e ~ 10¹⁰⁻¹¹ K).

Each = volume-density profile + emission model, emits spectral
radiance. Packages: `pkg32-slim-disk.md`, `pkg33-adaf.md`.

### 4.3 Synchrotron emission and jets

Plugin `plugins/emission/synchrotron.cpp`. Power-law electrons
N(E) ∝ E^(-p), j_ν ∝ n_0 B^((p+1)/2) ν^(-(p-1)/2). Doppler boost
I_ν = D³ I'_ν' where D = 1/(γ(1 − β cos θ)).

For γ=10 head-on, approaching jet ×10⁵, counter-jet ×10⁻⁸. Most
visually dramatic effect Astroray will produce.

Package: `pkg34-synchrotron.md`.

### 4.4 HII regions and emission nebulae

Spectral pipeline's natural fit. Lines: Hα 656.3nm, Hβ 486.1nm,
[OIII] 500.7/495.9nm, [NII] 658.4/654.8nm.

Preprocessing: Python `pyCloudy` generates emissivity tables
j_ν(ρ, T, U, λ) as a 4D lookup. Astroray's plugin samples per-voxel.

Packages: `pkg35-cloudy-tables.md` (Python preprocessing),
`pkg36-hii-plugin.md`.

### 4.5 Simulation data import

Two flavors: observational (FITS) and simulation (HDF5, numpy).

**FITS** via EleFits (or raw CFITSIO). A FITS image becomes either a
volumetric density or a plane-sky texture. Used for loading real
Hubble/JWST cubes and overlaying models.

**HDF5/numpy from yt**: user preprocesses a simulation snapshot in
Python:
```python
import yt
ds = yt.load("snapshot_100.hdf5")
grid = ds.covering_grid(level=3, left_edge=[0,0,0], dims=[256,256,256])
np.save("density.npy", grid["density"].value)
np.save("temperature.npy", grid["temperature"].value)
```
Astroray's `SimulationVolume` plugin loads these `.npy` files directly.

**SPH data** needs kernel interpolation to a grid. Wendland C4 kernel;
~100 lines, no external dep.

Packages: `pkg37-fits-loader.md`, `pkg38-hdf5-loader.md`,
`pkg39-sph-to-volume.md`.

### 4.6 Gravitational lensing

Weak lensing from a mass distribution can be rendered as a
screen-space deflection — for each camera ray, integrate the lensing
deflection along the line of sight and offset the background sample.
Much cheaper than full GR ray tracing, good enough for cluster
lensing.

Strong lensing uses the GR integrator with a point-mass or NFW-profile
metric (reuses the machinery from Kerr).

Plugin: `plugins/lensing/weak.cpp`, `plugins/lensing/cluster.cpp`.

Package: `pkg40-weak-lensing.md` (strong lensing inherits from Kerr
machinery — no extra package).

### 4.7 Synthetic telescope observations (PSF, noise)

A post-process plugin that convolves the final image with a
wavelength-dependent PSF and adds a noise model matching a specified
detector.

- PSF input: Python preprocessing via WebbPSF generates a FITS cube
  (PSF per wavelength). Astroray loads and applies via FFT convolution.
- Noise: Gaussian read + Poisson photon + dark current. Standard
  parameters (CCD gain, read noise in e⁻, exposure time).

Plugin: `plugins/postprocess/telescope.cpp`.

Package: `pkg41-telescope-postprocess.md`.

## Migration strategy

### Phase 4A: Kerr (2 weeks, track A)

Existing Schwarzschild code becomes the reference. Kerr is the new
plugin. Cross-validate against GYOTO for a handful of test scenes.

### Phase 4B: Emission plugins (3–4 weeks, track B)

Slim disk, ADAF, synchrotron jets, HII regions. Each a week of
Copilot-agent work with careful review. Run in parallel — they don't
conflict.

### Phase 4C: Data import (2 weeks, track B)

FITS, HDF5, SPH-to-volume. Mostly I/O plumbing; Copilot agent work.

### Phase 4D: Lensing + telescope (1 week, track A)

## Acceptance criteria

- [ ] Kerr BH a=0.9 renders with correct frame-dragging asymmetry
      vs GYOTO reference.
- [ ] Synchrotron jet shows 10⁵ Doppler-boost asymmetry.
- [ ] HII plugin line ratios within 10% of CLOUDY predictions.
- [ ] FITS and HDF5 loaders import real simulation snapshots.
- [ ] Telescope post-process matches reference Gaussian convolution.

## Non-goals

- **Full numerical relativity.** We ray-trace given metrics; we do not
  solve Einstein equations.
- **Full MHD simulations.** We visualize simulation output; we do not
  run simulations.
- **Instrument-calibrated PSFs.** "Good enough for outreach and rough
  predictions" — not EHT publication-grade.
