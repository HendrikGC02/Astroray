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
- 2026-09-22: Codex Terra review defects applied (planning session).

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
| `include/astroray/sph_kernel.h` | Header-only Wendland C4 kernel + conservative density deposition and Shepard-normalised interpolation; no external deps. |
| `scripts/sph_to_volume.py` | Convert SPH snapshot fields → dense `.npy` (C-order float32) or `.vdb` via Blender 5.2's bundled `openvdb`; emit the full `set_volume_grid` transform payload; record provenance and resampling loss. |
| `tests/test_sph_kernel.py` | Kernel, conservation, boundary, convergence, transform and warning tests; synthetic particles created at test time. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Bind `sph_to_grid(positions, h, values, masses, densities, grid_dims, bbox_min, bbox_max) -> float32 (nz, ny, nx)` beside `set_volume_grid`. |
| `scripts/README.md` | Register `scripts/sph_to_volume.py` (new reusable-script rule). |
| `.astroray_plan/docs/STATUS.md` | Mark pkg49 done. |
| `CHANGELOG.md` | Add pkg49 entry. |

### Key design decisions

- **Output contract (full `set_volume_grid` payload).** The script emits the
  dense C-order float32 `(nz, ny, nx)` density *and* the transforms the engine
  requires — `bbox_min` `(i, j, k)` (active-block minimum), `index_to_object`
  and `object_to_world` (row-major 4×4 affines; exactly the tuple
  `PyRenderer.set_volume_grid` in `module/blender_module.cpp` consumes) — plus
  pkg48 provenance. Physical voxel volume is
  `dV = |det(index_to_object[:3, :3])|`; world placement comes from
  `object_to_world`. Both transforms are emitted in the sidecar/metadata and
  asserted by tests. Retire `DensityGrid`/`SimulationVolume`; pkg48 supplies
  read/write adapters, units and provenance, pkg49 only resamples.
- **`.vdb` is a representation choice, not proof of fidelity.** The script records
  the resampling step and reports mass before/after plus min/max, per pkg48's
  provenance contract. `.npy` and `.vdb` must carry identical values *and*
  identical transforms.
- **Kernel: Wendland C4** (Dehnen & Aly 2012, Table 1, 3D):

  ```
  W(r,h) = (495 / (32*pi)) * h^-3 * (1-q)_+^6 * (1 + 6q + (35/3)q^2),  q = r/h
  support q <= 1,  integral of W * 4*pi*r^2 dr = 1
  ```

  Here `h` is the support radius. Simulation codes define `h` differently
  (e.g. GADGET's cubic-spline support is `2h`); the script takes an explicit
  `h_convention` argument and records it in provenance.
- **Splatting: conservative deposition + Shepard interpolation (two fields).**
  Westover (1990) footprint AABB on the Monaghan (1992) estimate, per the
  research-doc pseudocode. *Conservative density deposition:*
  `rho(x) = Σ_i m_i W(x − x_i, h_i)`, no division — this is the field that
  carries the mass meaning. *Shepard (1968) interpolation:* for non-mass fields
  (`values`, e.g. `T`, `v`), accumulate `Σ_i value_i W_i V_i` and `Σ_i W_i V_i`
  per cell, divide by the weight (vacuum cells → 0), with `V_i = m_i / rho_i`;
  interpolation only, with no conservation claim.
- **Boundary policy: pad-and-report.** The deposition grid is internally padded
  by `ceil(h_max / dx)` ghost cells per axis (`dx` the smallest cell edge) so no
  in-domain particle support is truncated by index clamping; ghost cells are
  cropped after deposition. A particle whose support misses the requested domain
  deposits nothing and its mass is counted in `mass_out`; the script reports
  `mass_in = Σ m_i − mass_out` and `|∫rho dV − mass_in| / mass_in`. Tests place
  one particle at the interior, on a face, on a corner and fully outside,
  asserting each lands in the expected category and that the accounting identity
  holds.
- **Smoothing-length-vs-grid-resolution warning.** Warn when a particle's support
  radius spans fewer than ~2 voxels (undersampled kernel), reporting the affected
  fraction and suggesting a finer grid or larger `h`. This is the known
  resolution floor for a kernel-deposited field (Price 2012; Dehnen & Aly 2012).
- **First measurable deliverable.** A kernel-normalisation figure: numerical
  quadrature gives `∫W dV = 1` within **1e-4**, and *separately* the dimensionless
  central amplitude `h^3·W(0) = 495/(32*pi)` (Dehnen & Aly 2012, Table 1) within
  1e-4. These are two distinct checks, not one.

#### Phase 1 — kernel, deposition and boundary accounting

`sph_kernel.h` plus the `sph_to_grid` binding; kernel-normalisation (`∫W dV = 1`
and `h^3·W(0)` separately), symmetry, uniform-density, conservative-mass and
face/corner/outside boundary tests.

#### Phase 2 — conversion script

`scripts/sph_to_volume.py`: HDF5/NumPy input, code-`h` mapping, `.npy` and `.vdb`
output, full transform payload (`bbox_min`, `index_to_object`, `object_to_world`),
provenance and resampling-loss report, undersampling warning.

---

## Acceptance criteria

- [ ] Kernel normalisation: numerical quadrature gives `∫W dV = 1` within 1e-4,
      and separately `h^3·W(0) = 495/(32*pi)` (Dehnen & Aly 2012, Table 1
      central amplitude) within 1e-4.
- [ ] Conservative mass: `|∫rho dV − mass_in| / mass_in < 0.5%` with
      `rho(x) = Σ_i m_i W(x − x_i, h_i)` and `mass_in = Σ m_i − mass_out`.
      Shepard weights are interpolation only and are not a conservation check.
- [ ] Boundary accounting: interior, face-centred, corner and fully-outside
      particles each deposit the expected share; `mass_out` equals the mass of
      supports that miss the domain; no silent AABB clamping.
- [ ] Resolution convergence (fixture below): voxel volume
      `dV = |det(index_to_object[:3, :3])|`; both grids satisfy the conservative
      mass bound; halving the voxel size changes the integrated density by < 1%;
      and the restricted-grid L1 error of the 32³ field against the
      mass-conserving 2×2×2 restriction of the 64³ field is < 2%
      (frozen 2026-09-22, lead may adjust). Integrated totals alone are not
      convergence evidence.
- [ ] Smoothing-length-vs-grid-resolution warning fires when the support radius
      spans < 2 voxels and names the affected particle fraction.
- [ ] Compact support: kernel returns exactly 0 for `q >= 1`; non-negative on
      `[0, 1]`.
- [ ] Single particle: max relative asymmetry < 1e-5 across all axes; peak at the
      centre; exactly 0 beyond the support radius.
- [ ] Uniform density: N=1000 equal-mass particles in `[0,1]^3` → 32³ grid,
      max/min < 1.05 (1-cell boundary margin).
- [ ] Transform payload: the script emits `bbox_min`, `index_to_object` and
      `object_to_world`; tests assert `dV` equals the requested voxel volume,
      round-trip the affines, and load the full tuple through `set_volume_grid`
      (renders without error).
- [ ] `.vdb` round-trips through Blender's bundled `openvdb` with matching shape
      and matching transforms.
- [ ] Python script NumPy fallback writes a `.npy` of the right shape and
      plausible values.
- [ ] Performance: N=1×10⁵ particles → 128³ grid in < 10 s on a single core.
- [ ] All existing tests pass; ≥ 6 new tests.

### Concrete test data

| Test | Particles | Grid | Created by |
|---|---|---|---|
| Normalisation quadrature | kernel only | N/A | Numerical integration in Python (`∫W dV` and `h^3·W(0)`) |
| Uniform distribution | N=1000, unit cube, equal mass | 32³ | `np.random.default_rng(42).uniform(0,1,(1000,3))` |
| Single particle | N=1, unit-cube centre, `h=0.1` | 32³ | inline in test |
| Boundary accounting | 1 interior + 1 face + 1 corner + 1 outside, `h=0.2` | 32³, unit cube | inline in test |
| Resolution convergence | N=1000 unit cube, fixed `h_i = 0.25` (frozen 2026-09-22, lead may adjust; support spans ≥ 8 voxels at 32³) | 32³ vs 64³ | same particles, halved voxel size; `dV` from `index_to_object` |
| Transform payload | N=100 | 16³ | inline in test |
| Output format | N=100 | 16³ | inline in test |

Reference for convergence: field-error metric is the restricted-grid L1 error
against the mass-conserving 2×2×2 restriction of the 64³ field, with the pad-and-
report boundary fixture; mass error is reported separately. All data generated
inline in tests; no binaries committed.

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

- [ ] Implement Wendland C4 kernel + conservative deposition + Shepard
      interpolation in `sph_kernel.h`.
- [ ] Bind `sph_to_grid` in `module/blender_module.cpp`.
- [ ] Write `scripts/sph_to_volume.py` (C++ call + NumPy fallback; `.npy`/`.vdb`;
      transform payload; provenance; undersampling warning).
- [ ] Write tests (normalisation, conservation, boundary, convergence, transform,
      warning, symmetry, format).
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md, scripts/README.md.

---

## Lessons

*(Fill in after the package is done.)*
