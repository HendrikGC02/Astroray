# pkg113 Phase 1 — GPU photon-store research (uniform spatial hash grid)

Research notes for the GPU port of the photon-map caustic STORE + query
(pkg113 Phase 1). Satisfies CLAUDE.md §6: paper + license-compatible reference
impl cited before code; the CUDA cites file:line back to these sources.

## Store decision (already made by owner, not re-litigated here)

`packages/pkg113-gpu-photon-map-caustics.md` Decisions §2 and
`.astroray_plan/docs/cpu-gpu-parity-status.md` Decisions §2 (owner, 2026-05-30):

> Build the GPU store as a **uniform spatial hash grid** (pbrt SPPM style —
> far friendlier to GPU parallelism than the CPU balanced kd-tree) and gate on
> SSIM/energy vs the CPU result. Do **not** port the kd-tree for bit-exact
> parity.

Phase 1 therefore implements the hash-grid build + a device radius/k-NN query
that mirrors the **density-estimate semantics** of the CPU
`photon_map.h::estimateIrradiance` (Jensen 2000 §3.1 Eq. 8) — NOT bit-exact
kd-tree parity. The hash grid returns the *same neighbor set within a fixed
radius* as a brute-force radius search, so a radius query is exactly verifiable
against a numpy oracle; the irradiance estimate then matches the CPU disk-area
density factor within float tolerance.

## Papers

- **Jensen, "Global Illumination using Photon Maps", EGWR 1996**, DOI
  `10.1007/978-3-7091-7484-5_3` — the photon map: diffuse-surface deposition +
  k-NN density-estimate radiance.
- **Jensen, "A Practical Guide to Global Illumination using Photon Maps",
  SIGGRAPH 2000 Course 8**, §3.1 Eq. 8 (radiance/irradiance estimate). The CPU
  `photon_map.h` mirrors this; the GPU store reproduces the same Eq. 8 estimate
  over the radius-gathered neighbor set.

## Reference implementation (license-clean)

- **pbrt-v3** `src/integrators/sppm.cpp` (SPDX **BSD-2-Clause**, MIT-compatible).
  The canonical uniform spatial-hash-grid build for SPPM. We mirror three
  functions verbatim (math identical; adapted to GVec3 / device code):

  - **`ToGrid`** — map a world point inside the grid AABB to integer grid
    coords:
    ```cpp
    static bool ToGrid(const Point3f &p, const Bounds3f &bounds,
                       const int gridRes[3], Point3i *pi) {
        bool inBounds = true;
        Vector3f pg = bounds.Offset(p);               // (p-min)/(max-min)
        for (int i = 0; i < 3; ++i) {
            (*pi)[i] = (int)(gridRes[i] * pg[i]);
            inBounds &= ((*pi)[i] >= 0 && (*pi)[i] < gridRes[i]);
            (*pi)[i] = Clamp((*pi)[i], 0, gridRes[i] - 1);
        }
        return inBounds;
    }
    ```
  - **`hash`** — integer grid coords → bucket index, with the three large
    primes (Teschner et al. 2003 "Optimized Spatial Hashing", reused by pbrt):
    ```cpp
    inline unsigned int hash(const Point3i &p, int hashSize) {
        return (unsigned int)((p.x * 73856093) ^ (p.y * 19349663) ^
                              (p.z * 83492791)) % hashSize;
    }
    ```
    Primes: **73856093, 19349663, 83492791**.
  - **grid resolution** from the AABB diagonal and the search radius:
    ```cpp
    Vector3f diag = gridBounds.Diagonal();
    Float maxDiag = MaxComponent(diag);
    int baseGridRes = (int)(maxDiag / maxRadius);
    for (int i = 0; i < 3; ++i)
        gridRes[i] = max((int)(baseGridRes * diag[i] / maxDiag), 1);
    ```

  We DROP pbrt's progressive radius reduction (γ / rNew = r√…) and per-pixel
  visible points — Phase 1 is a fixed-radius single-pass store (same
  non-progressive simplification the CPU chain already takes; pkg109 research
  note §"Reference implementation"). pbrt stores *visible points* in the grid
  and shoots photons against them; we store *photons* in the grid and query at
  receiver points — the data structure and hash are identical, only the roles of
  "stored" vs "queried" swap. That is the standard photon-map↔SPPM duality.

## Density estimate (mirrors CPU `photon_map.h`)

Within a fixed radius `r`, the Jensen 2000 §3.1 Eq. 8 irradiance estimate is

    E(x) = (1 / (π r²)) · Σ_{p : |x−x_p| < r} ΔΦ_p

The CPU `estimateIrradiance` additionally applies the §3.2.1 cone filter using
the k-th nearest distance as `r`. For the **Phase-1 parity harness** we compare
the simpler fixed-radius density (no cone filter) on both sides so the oracle is
unambiguous; the cone-filtered/k-NN form is a Phase-2/3 concern (it needs the
emission pipeline to produce realistic photon distributions anyway). The device
query returns BOTH:
  1. the neighbor index set within `radius` (exact set-match vs numpy oracle),
  2. the fixed-radius irradiance estimate `E` (float-tolerance vs numpy oracle).

## Astroray reuse points (audited)

| What | Where | Note |
|---|---|---|
| `GVec3` device vec3 | `include/astroray/gpu_types.h:20` | photon position / query point |
| `XYZ` CPU struct | `include/astroray/spectrum.h:29` | photon power on host side |
| host→device upload helper pattern | `src/gpu/scene_upload.cu:39` | `cudaMalloc`+`cudaMemcpy` |
| `CUDA_CHECK` macro | `src/gpu/scene_upload.cu:26` | error wrapping |
| host-callable CUDA fn → pybind | `src/gpu/wavefront/gpu_wavefront_snapshot.{h,cu}` + `module/blender_module.cpp:3257` | the exact binding pattern Phase-1 mirrors |
| GPU test skip pattern | `tests/test_pkg64_gpu_cpu_parity.py:41-46` | skip when `__features__["cuda"]` false |
| CPU kd-tree oracle test | `tests/test_photon_map.py` | numpy float64 brute-force pattern to mirror |

## Phase-1 deliverables (scope guard)

STORE + query only. NOT emission/bounce (Phase 2), NOT integrator gather wiring
(Phase 3). A single new `.cu` (`src/gpu/photon_store.cu`) + its header
(`include/astroray/gpu_photon_store.h`) + a pybind test binding
(`_gpu_photon_store_query`) + a CUDA-gated unit test
(`tests/test_gpu_photon_store.py`).

## Integration risks (carried forward to the parent build/verify)

- **CI has no GPU** (memory `ci_has_no_gpu_runtime_blindspot`): the unit test
  skips on CI; correctness must be RTX-`/verify`-ed.
- **Stale .pyd** (memory `stale_pyd_locations`): rebuild + check
  `astroray.__file__` before trusting the test.
- The CUDA frontend syntax-check CI job (`cuda-syntax-check`) compiles every
  `.cu` via `nvcc -c`; it will catch frontend errors at PR time but is a
  backstop — parent must run the full local CUDA build.
