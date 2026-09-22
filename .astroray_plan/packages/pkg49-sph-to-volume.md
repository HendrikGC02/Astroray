# pkg49 — SPH-to-Volume Conversion

**Pillar:** 4
**Track:** B
**Status:** paused — Pillar 4 (Stage 3); rewritten 2026-09-22
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg48

---

## Goal

Before: SPH snapshots (AREPO, GADGET, SWIFT, Phantom) cannot enter Astroray, and
the old pkg49 targeted a retired bespoke `DensityGrid`/`SimulationVolume` type.
After: a header-only Wendland C4 splatting kernel plus a Python conversion script
turn particle data into a dense C-order float32 array for
`PyRenderer.set_volume_grid` (`module/blender_module.cpp`), or into a
Blender-native `.vdb`. No engine plugin type is added.

---

## Context

Pillar 4 ingest is conversion tooling, not an engine reader: dense NumPy grids
already reach the engine through `set_volume_grid`, so a bespoke reader needs a
demonstrated gap. pkg48 owns the HDF5/NumPy adapters, units, transforms and
provenance contract; pkg49 owns only the particle→grid resampling. This is Stage 3
groundwork, behind the Stage 0 gate work; the thaw rule permits the spec now.

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.

---

## Reference

- Design: `.astroray_plan/docs/pillar4-data-io-research.md §§1, 5, 6` (grid
  representation, kernel formula, splatting pseudocode, synthetic test data).
- Stage plan: `.astroray_plan/docs/stage-plan-2026-09-22.md §4` (Track N ingest).
- Pillar context: `.astroray_plan/docs/astrophysics.md`.
- External:
  - Monaghan (1992), *ARA&A* 30, 543, DOI 10.1146/annurev.aa.30.090192.002551 —
    SPH smoothing estimate and kernel conventions.
  - Dehnen & Aly (2012), *MNRAS* 425, 1068, DOI 10.1111/j.1365-2966.2012.21439.x
    — Wendland C4 functional form and normalisation (Table 1).
  - Shepard (1968), *ACM 23rd Nat. Conf.*, DOI 10.1145/800186.810616 — Shepard
    normalisation for scattered data.
  - Westover (1990), *SIGGRAPH '90*, 367–376, DOI 10.1145/97879.97919 —
    footprint-evaluation splatting.
  - [yt](https://yt-project.org/) SPH deposition (BSD-3-Clause) — algorithm
    cross-check only; no code copied.
  - [Splotch](https://github.com/splotch/splotch) (GPLv2) — reference only;
    **do not mirror**.

---

## Prerequisites

- [ ] pkg48 conversion tooling landed: HDF5/NumPy adapters plus the
      field/units/provenance contract.
- [ ] `PyRenderer.set_volume_grid` accepts a dense `(nz, ny, nx)` float32 array
      (it does today).
- [ ] Build passes on main; all existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/sph_kernel.h` | Header-only Wendland C4 kernel + Shepard-normalised scatter splatting; no external deps. |
| `scripts/sph_to_volume.py` | Convert SPH snapshot fields → dense `.npy` (C-order float32) or `.vdb` via Blender 5.2's bundled `openvdb`; record provenance and resampling loss. |
| `tests/test_sph_kernel.py` | Kernel, conservation, convergence and warning tests; synthetic particles created at test time. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Bind `sph_to_grid(positions, h, values, masses, densities, grid_dims, bbox_min, bbox_max) -> float32 (nz, ny, nx)` beside `set_volume_grid`. |
| `scripts/README.md` | Register `scripts/sph_to_volume.py` (new reusable-script rule). |
| `.astroray_plan/docs/STATUS.md` | Mark pkg49 done. |
| `CHANGELOG.md` | Add pkg49 entry. |

### Key design decisions

- **Output contract.** A dense C-order float32 array shaped `(nz, ny, nx)` —
  exactly what `PyRenderer.set_volume_grid` in `module/blender_module.cpp`
  consumes. Retire `DensityGrid`/`SimulationVolume`; pkg48 supplies read/write
  adapters, units and provenance, pkg49 only resamples.
- **`.vdb` is a representation choice, not proof of fidelity.** The script records
  the resampling step and reports mass before/after plus min/max, per pkg48's
  provenance contract. `.npy` and `.vdb` must carry identical values.
- **Kernel: Wendland C4** (Dehnen & Aly 2012, Table 1, 3D):

  ```
  W(r,h) = (495 / (32*pi)) * h^-3 * (1-q)_+^6 * (1 + 6q + (35/3)q^2),  q = r/h
  support q <= 1,  integral of W * 4*pi*r^2 dr = 1
  ```

  Here `h` is the support radius. Simulation codes define `h` differently
  (e.g. GADGET's cubic-spline support is `2h`); the script takes an explicit
  `h_convention` argument and records it in provenance.
- **Splatting: Westover footprint AABB + Shepard (1968) normalisation**, on the
  Monaghan (1992) smoothing estimate. For each particle, evaluate the kernel on
  the grid cells inside its support AABB, accumulate `value[i] * W * V[i]` and
  `W * V[i]` with `V[i] = mass[i] / density[i]`, then divide the field by the
  weight (0 in vacuum cells).
- **Smoothing-length-vs-grid-resolution warning.** Warn when a particle's support
  radius spans fewer than ~2 voxels (undersampled kernel), reporting the affected
  fraction and suggesting a finer grid or larger `h`. This is the known
  resolution floor for a kernel-deposited field (Price 2012; Dehnen & Aly 2012).
- **First measurable deliverable.** A kernel-normalisation figure: numerical
  quadrature of the Wendland C4 kernel reproduces the Dehnen & Aly (2012) Table 1
  3D constant `495/(32*pi)` within **1e-4**.

#### Phase 1 — kernel and conservation

`sph_kernel.h` plus the `sph_to_grid` binding; kernel-normalisation, symmetry,
uniform-density and mass-conservation tests.

#### Phase 2 — conversion script

`scripts/sph_to_volume.py`: HDF5/NumPy input, code-`h` mapping, `.npy` and `.vdb`
output, provenance and resampling-loss report, undersampling warning.

---

## Acceptance criteria

- [ ] First deliverable: kernel-normalisation figure; quadrature equals
      `495/(32*pi)` (Dehnen & Aly 2012, Table 1) within 1e-4.
- [ ] Total mass conserved within 0.5% after splatting (Shepard weights sum to
      the input `sum(mass)`).
- [ ] Resolution convergence: halving the voxel size changes the integrated
      density by < 1%.
- [ ] Smoothing-length-vs-grid-resolution warning fires when the support radius
      spans < 2 voxels and names the affected particle fraction.
- [ ] Compact support: kernel returns exactly 0 for `q >= 1`; non-negative on
      `[0, 1]`.
- [ ] Single particle: max relative asymmetry < 1e-5 across all axes; peak at the
      centre; exactly 0 beyond the support radius.
- [ ] Uniform density: N=1000 equal-mass particles in `[0,1]^3` → 32³ grid,
      max/min < 1.05 (1-cell boundary margin).
- [ ] Output array loads through `set_volume_grid` and renders without error.
- [ ] `.vdb` round-trips through Blender's bundled `openvdb` with matching shape.
- [ ] Python script NumPy fallback writes a `.npy` of the right shape and
      plausible values.
- [ ] Performance: N=1×10⁵ particles → 128³ grid in < 10 s on a single core.
- [ ] All existing tests pass; ≥ 6 new tests.

### Concrete test data

| Test | Particles | Grid | Created by |
|---|---|---|---|
| Normalisation quadrature | kernel only | N/A | Numerical integration in Python |
| Uniform distribution | N=1000, unit cube, equal mass | 32³ | `np.random.default_rng(42).uniform(0,1,(1000,3))` |
| Single particle | N=1, unit-cube centre, `h=0.1` | 32³ | inline in test |
| Resolution convergence | N=1000 | 32³ vs 64³ | same particles, halved voxel size |
| Output format | N=100 | 16³ | inline in test |

All data generated inline in tests; no binaries committed.

---

## Non-goals

- No runtime SPH sampling in the engine: no ray-marching through particles;
  pre-gridding only.
- No new engine-side SPH reader/plugin: dense arrays and `.vdb` are the
  interfaces; an engine reader needs a demonstrated gap.
- No AMR-to-uniform regridding; use yt.
- No simulation-code-specific file-format parsing in C++; the Python script
  handles format I/O.
- No adaptive/octree grid; uniform grid only.
- No velocity-field Doppler shifting (velocity may be gridded as a separate
  field; spectral shifts are out of scope).

---

## Progress

- [ ] Implement Wendland C4 kernel + Shepard splatting in `sph_kernel.h`.
- [ ] Bind `sph_to_grid` in `module/blender_module.cpp`.
- [ ] Write `scripts/sph_to_volume.py` (C++ call + NumPy fallback; `.npy`/`.vdb`;
      provenance; undersampling warning).
- [ ] Write tests (normalisation, conservation, convergence, warning, symmetry,
      format).
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md, scripts/README.md.

---

## Lessons

*(Fill in after the package is done.)*
