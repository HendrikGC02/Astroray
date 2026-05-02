# pkg49 — SPH-to-Volume Conversion

**Pillar:** 4
**Track:** B (self-contained utility)
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg48 (SimulationVolume plugin)

---

## Goal

**Before:** SPH (Smoothed Particle Hydrodynamics) simulation data
consists of scattered particles, not a regular grid. Astroray's
`SimulationVolume` (pkg48) only reads uniform grids. Users with SPH
data (AREPO, GADGET, SWIFT, Phantom) must preprocess externally.

**After:** A C++ utility function and a Python convenience script
convert SPH particle data into a uniform 3D grid using Wendland C4
kernel interpolation. The output is a `.npy` file that
`SimulationVolume` can load directly. The C++ kernel is also available
at render time for direct particle splatting as an alternative to
pre-gridding.

---

## Context

SPH is one of the two dominant methods for astrophysical hydrodynamics
(the other being AMR grid codes). AREPO, GADGET-4, SWIFT, and Phantom
all output particle data with positions, smoothing lengths, and field
values. Converting to a grid is straightforward (~100 lines of kernel
evaluation) but must be done correctly to avoid aliasing and
normalisation artifacts.

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.5`
- Wendland 1995 — compactly-supported radial basis functions
- Price 2012 — "Smoothed Particle Hydrodynamics and
  Magnetohydrodynamics" (SPH kernel review, §2.1)
- Existing: `SimulationVolume` plugin from pkg48

---

## Prerequisites

- [ ] pkg48 is done: `SimulationVolume` loads `.npy` grids.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/sph_kernel.h` | Wendland C4 kernel implementation + grid splatting function. Header-only, ~100 lines. |
| `plugins/data/sph_to_grid.cpp` | `SPHToGrid` utility registered as a data-processing plugin. Reads particle data (positions, smoothing lengths, field values), outputs a uniform grid. |
| `scripts/sph_to_npy.py` | Python convenience script: reads particle data from HDF5 (GADGET/AREPO format), calls the C++ splatting via pybind11 (or does it in pure Python/NumPy as fallback), writes `.npy`. |
| `tests/test_sph_kernel.py` | Unit tests for kernel properties and grid conversion. |
| `tests/data/test_particles.npy` | Small synthetic particle dataset (1000 particles) for testing. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Expose `sph_to_grid(positions, smoothing_lengths, values, grid_dims, bbox)` function via pybind11. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg49 done. |
| `CHANGELOG.md` | Add pkg49 entry. |

### Kernel specification

**Wendland C4** in 3D:

    W(q) = (495 / 32π h³) · (1 − q)⁶ · (1 + 6q + 35q²/3)  for q ≤ 1
    W(q) = 0                                                  for q > 1

where q = r/h and h is the smoothing length. This kernel is:
- C4 continuous (smooth second derivatives).
- Compactly supported (exactly zero beyond r = h).
- Normalised: ∫ W(r) d³r = 1.
- Positive definite (no negative lobes; pairing instability-free).

### Grid splatting algorithm

For each particle i with position x_i, smoothing length h_i, and
field value A_i:

1. Find the axis-aligned bounding box of the particle's kernel
   support: [x_i − h_i, x_i + h_i] in each dimension.
2. Identify all grid cells that overlap this box.
3. For each overlapping cell at position x_j:
   - Compute q = |x_j − x_i| / h_i.
   - Add A_i · W(q) · V_particle to the cell's accumulator.
   - Add W(q) · V_particle to a normalisation accumulator.
4. After all particles: divide field accumulator by normalisation
   accumulator (scatter-gather normalisation).

V_particle = m_i / ρ_i is the particle volume (mass / density).
If density is the field being gridded, the result is self-consistent.

Complexity: O(N · (h/Δx)³) where Δx is the grid cell size. For
typical SPH data with h ~ 2–4 Δx, each particle touches ~64–512
cells. With 10⁶ particles at 256³ resolution, this takes ~1–10
seconds on a single core.

### Key design decisions

1. **Wendland C4, not cubic spline.** The cubic B-spline has negative
   lobes and is susceptible to the pairing instability. Wendland C4 is
   the modern standard (used by SWIFT, Phantom, and recent GADGET
   forks). It costs marginally more to evaluate but produces
   smoother, artifact-free grids.

2. **Pre-gridding as the primary path.** Direct particle rendering
   (splatting particles during ray marching) is more accurate but
   requires spatial indexing (kd-tree or hash grid) and is harder to
   integrate with the volume rendering path. Pre-gridding is simpler,
   produces a `.npy` that `SimulationVolume` already knows how to
   render, and is fast enough for the expected data sizes.

3. **Python fallback.** The Python script can run in pure NumPy mode
   (slower but no C++ dependency) or call the pybind11-exposed C++
   function (fast). This flexibility means users can preprocess data
   even without building Astroray's C++ module.

4. **No particle format parsing in C++.** The C++ function takes raw
   arrays (positions, smoothing lengths, values). The Python script
   handles format-specific I/O (GADGET HDF5 group names, AREPO Voronoi
   mesh centres, etc.). This keeps the C++ side format-agnostic.

---

## Acceptance criteria

- [ ] Wendland C4 kernel is normalised: numerical integration over a
      fine grid yields 1.0 ± 1e-4.
- [ ] Kernel is exactly zero for q > 1.
- [ ] A uniform-density particle distribution produces a uniform grid
      (max/min ratio < 1.01).
- [ ] A single particle at the grid centre produces a smooth,
      symmetric, bell-shaped density field.
- [ ] Grid output is a valid `.npy` file loadable by `SimulationVolume`.
- [ ] Python script runs in fallback mode (no C++ module) and produces
      correct output.
- [ ] Splatting 10⁵ particles to a 128³ grid completes in < 10 seconds
      on a single core.
- [ ] All existing tests pass.
- [ ] ≥6 new tests covering: kernel normalisation, compact support,
      uniform distribution, single particle, grid output format,
      Python fallback.

---

## Non-goals

- Do not implement direct SPH particle rendering (ray-marching through
  particles with on-the-fly kernel evaluation). That is a future
  optimisation.
- Do not implement AMR-to-uniform regridding. Use yt for that.
- Do not parse simulation-code-specific file formats in C++. The Python
  script handles format I/O.
- Do not implement adaptive grid resolution (octree). Uniform grid
  only.
- Do not implement velocity field interpolation for Doppler shifting.
  Velocity can be gridded as a separate field but is not used for
  spectral shifts in this package.

---

## Progress

- [ ] Implement Wendland C4 kernel in `sph_kernel.h`.
- [ ] Implement grid splatting function.
- [ ] Register as data-processing plugin.
- [ ] Expose via pybind11.
- [ ] Write Python convenience script.
- [ ] Generate synthetic test particles.
- [ ] Write tests.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*
