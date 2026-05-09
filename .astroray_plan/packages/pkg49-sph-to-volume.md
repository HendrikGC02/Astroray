# pkg49 — SPH-to-Volume Conversion

**Pillar:** 4  
**Track:** B (self-contained utility)  
**Status:** open  
**Estimated effort:** 1 session (~3 h)  
**Depends on:** pkg48 (SimulationVolume plugin, DensityGrid type)

**Reference research:** `.astroray_plan/docs/pillar4-data-io-research.md §§1, 5, 6`  
(DensityGrid type, cubic spline kernel formula, Shepard splatting pseudocode,
test data strategy — read before writing any SPH code)

---

## Reference Implementations

| Source | License | What we use | What we do NOT mirror |
|---|---|---|---|
| Monaghan (1992), *Ann. Rev. Astron. Astrophys.* 30, 543 | Public domain (journal article) | Cubic B-spline kernel formula, normalisation constant | N/A |
| Price (2012), arXiv:1012.1885 | Public domain (arXiv preprint) | Kernel review, Eq. (4)-(5) for cubic spline in 3D | N/A |
| Westover (1990), *SIGGRAPH '90* pp. 367-376 | Public domain (conference paper) | Footprint-evaluation splatting algorithm | N/A |
| [yt SPH deposition](https://yt-project.org/) | BSD-3-Clause | Algorithm cross-check only; Shepard normalisation idea | No C++ code from yt |
| [Splotch](https://github.com/splotch/splotch) SPH renderer | GPLv2 | **Do not mirror.** Algorithm reference only (check license before any use). | No code from Splotch |

**Kernel math and splatting algorithm are from public-domain papers; no
mirroring question arises.** yt is a Python cross-check reference only.

---

## Goal

**Before:** SPH simulation data consists of scattered particles. `SimulationVolume`
(pkg48) reads only uniform grids. Users with AREPO, GADGET, SWIFT, or Phantom
data must preprocess externally.

**After:** A C++ utility function and a Python convenience script convert SPH
particle data into a uniform 3D grid using cubic B-spline kernel splatting. The
output is a `.npy` file that `SimulationVolume` loads directly. No new C++ plugin
interface is needed — the utility is exposed via pybind11.

---

## Context

SPH is one of the two dominant methods for astrophysical hydrodynamics. AREPO,
GADGET-4, SWIFT, and Phantom all output particle data with positions, smoothing
lengths, and field values. Converting to a uniform grid via kernel splatting is
~100 lines of C++ and is the standard preprocessing step.

---

## Prerequisites

- [ ] pkg48 done: `SimulationVolume` loads `.npy` grids and `DensityGrid` struct exists.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/sph_kernel.h` | Cubic B-spline kernel + Shepard splatting. Header-only, ~100 lines. No external deps. |
| `plugins/data/sph_to_grid.cpp` | `SPHToGrid` function registered and exposed via pybind11. |
| `scripts/sph_to_npy.py` | Python convenience script: reads particle data from HDF5 (GADGET/AREPO format), calls C++ splatting or pure-NumPy fallback, writes `.npy`. |
| `tests/test_sph_kernel.py` | Unit and integration tests. Synthetic particles created at test time. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Expose `sph_to_grid(positions, smoothing_lengths, values, masses, densities, grid_dims, bbox_min, bbox_max)` via pybind11. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg49 done. |
| `CHANGELOG.md` | Add pkg49 entry. |

### CMake recipe

No new CMake feature flag needed. `sph_kernel.h` is header-only with no external
dependencies. `sph_to_grid.cpp` is compiled unconditionally as part of the base
build.

```cmake
# No option() needed — SPH splatting has no external deps
target_sources(astroray PRIVATE plugins/data/sph_to_grid.cpp)
```

**Codex-ready immediately** — no dep find_package to verify.

### Kernel specification

**Cubic B-spline kernel (Monaghan 1992, §2; Price 2012 Eq. 4-5):**

```
W(r, h) = (1 / πh³) × w(q),    q = r / h

         ⎧ 1 − (3/2)q² + (3/4)q³,   0 ≤ q < 1
w(q) =  ⎨ (1/4)(2 − q)³,           1 ≤ q < 2
         ⎩ 0,                        q ≥ 2
```

Compact support: `r ∈ [0, 2h]`.  
Normalisation: `∫₀^{2h} W(r,h) 4πr² dr = 1` (analytically verified;
see research note §5 for the integral computation).

```cpp
// sph_kernel.h
inline float cubic_spline_kernel(float q) {
    if (q >= 2.0f) return 0.0f;
    if (q >= 1.0f) return (1.0f / float(M_PI)) * 0.25f * std::pow(2.0f - q, 3.0f);
    return (1.0f / float(M_PI)) * (1.0f - 1.5f*q*q + 0.75f*q*q*q);
    // caller divides by h³ for the full W(r,h)
}
```

**Why cubic spline over Wendland C4:** The cubic spline (support radius 2h) is
the canonical reference kernel for SPH splatting (Monaghan 1992; all major
textbook treatments). Wendland C4 (Dehnen & Aly 2012) has better spectral
properties for particle-based simulation integrators but is not required for
grid pre-processing, where the Shepard normalisation already corrects for
boundary effects. Use cubic spline for simplicity and textbook traceability.
If direct particle rendering is added later (ray-marching through particles),
revisit and switch to Wendland C4.

### Splatting algorithm

Westover (1990) footprint evaluation + Shepard (1968) normalisation:

```
Input:
  N particles: pos[3], h (smoothing length), value, mass, density
  Grid: nx × ny × nz cells, bbox_min[3], bbox_max[3]
  cell_size = (bbox_max - bbox_min) / (nx, ny, nz)
  particle_volume V[i] = mass[i] / density[i]

Output: field[nx, ny, nz]

Algorithm:
  field[...] = 0;  weight[...] = 0

  for i in 0..N-1:
    # kernel support AABB in grid index space
    for d in {x, y, z}:
      j_min[d] = max(0, floor((pos[i][d] − 2*h[i] − bbox_min[d]) / cell_size[d]))
      j_max[d] = min(n[d]−1, ceil((pos[i][d] + 2*h[i] − bbox_min[d]) / cell_size[d]))

    for jx in j_min[0]..j_max[0]:
      for jy in j_min[1]..j_max[1]:
        for jz in j_min[2]..j_max[2]:
          cell_centre = bbox_min + (jx+0.5, jy+0.5, jz+0.5) * cell_size
          r = |cell_centre − pos[i]|
          q = r / h[i]
          w_val = cubic_spline_kernel(q) / (h[i]*h[i]*h[i])   # full W(r,h)
          field[jx,jy,jz]  += value[i] * w_val * V[i]
          weight[jx,jy,jz] += w_val * V[i]

  # Shepard normalisation
  for all j:
    field[j] = (weight[j] > 0) ? field[j] / weight[j] : 0.0f
```

Output is a `DensityGrid` (flat C-order float array + shape + bbox) that
`SimulationVolume` (pkg48) renders directly.

---

## Acceptance criteria

- [ ] Kernel normalisation: numerical quadrature of W(r,h) on a fine spherical grid yields 1.0 ± 1e-4.
- [ ] Compact support: `cubic_spline_kernel(q)` returns exactly 0.0 for all `q ≥ 2.0`.
- [ ] Kernel non-negativity: `cubic_spline_kernel(q) ≥ 0` for all `q ∈ [0, 2]`.
- [ ] Uniform density: N=1000 particles uniformly distributed in [0,1]³ with equal mass → 32³ grid with max/min ratio < 1.05 (boundary cells excluded by 1-cell margin).
- [ ] Single particle: one particle at the grid centre → grid values are symmetric across all three axes (max asymmetry < 1e-5 relative); peak at centre; exactly 0 beyond support radius.
- [ ] Grid output: result is a valid `DensityGrid` loadable by `SimulationVolume` (pkg48 integration test).
- [ ] Python script runs in fallback mode (no C++ module, pure NumPy) and produces a `.npy` file with correct shape and plausible values.
- [ ] Performance: splatting N=1×10⁵ particles to a 128³ grid completes in < 10 seconds on a single core.
- [ ] All existing tests pass.
- [ ] ≥ 6 new tests: kernel normalisation, compact support, non-negativity, uniform distribution, single particle symmetry, grid output format.

### Concrete test data

| Test | Particles | Grid | Created by |
|---|---|---|---|
| Normalisation quadrature | N/A — kernel function only | N/A | Numerical integration in Python |
| Uniform distribution | N=1000, unit cube, equal mass | 32³ | `np.random.default_rng(42).uniform(0,1,(1000,3))` |
| Single particle | N=1, centre of unit cube | 32³ | `pos=[[0.5,0.5,0.5]], h=[0.1]` |
| Output format check | N=100 | 16³ | Generated inline in test |

All data generated inline in tests; no files committed.

---

## Non-goals

- No direct SPH particle rendering (ray-marching through particles on-the-fly). Pre-gridding only.
- No AMR-to-uniform regridding. Use yt for that.
- No simulation-code-specific file format parsing in C++. Python script handles format I/O.
- No adaptive grid resolution (octree). Uniform grid only.
- No velocity field Doppler shifting. Velocity can be gridded as a separate field but spectral shifts are out of scope for this package.

---

## Progress

- [ ] Implement cubic B-spline kernel in `sph_kernel.h`.
- [ ] Implement Shepard splatting function.
- [ ] Expose via pybind11 in `sph_to_grid.cpp`.
- [ ] Write Python convenience script (C++ call + NumPy fallback).
- [ ] Write tests.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*
