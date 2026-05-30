# pkg109 — World-space photon-map core

**Pillar:** 3 (Light transport)
**Track:** A (CPU integrator + numerical)
**Status:** done (PR #395 / `bc3464b`, 2026-05-30) — balanced kd-tree + k-NN density estimate; C++ validated vs numpy oracle; prism regression reproduced (hue 0.750, coverage 0.615); full suite 1155 passed.
**Estimated effort:** S/M (~2-3 days)
**Depends on:** pkg106 (forward `light_tracer_caustic` exists as the emission stub)

---

## Goal

pkg106 shipped a clean prism rainbow via a **special-case** forward light-tracer
(`plugins/integrators/light_tracer_caustic.cpp`): it deposits photons into a flat
2D (x,z) grid that **only** works for a horizontal floor receiver, and only for
an explicit 2-face prism refraction. The path to "drop ANY glass object + light →
caustics on ANY surface" starts by replacing that flat grid with a **general
world-space photon map** (a kd-tree of photons on diffuse surfaces) that supports
k-nearest-neighbour density estimation at an arbitrary query point/normal.

This package is storage-only: keep the existing 2-face emission, swap the backend
from the 2D grid to the kd-tree, and reproduce the prism band (regression-safe).

## Approach (cite — CLAUDE.md §6)

- **Jensen 1996, "Global Illumination using Photon Maps", EGWR.** The canonical
  photon-map: store `Photon{position, incident_dir, power (hero-λ weighted XYZ or
  spectral), lambda}` in a balanced kd-tree; query = k-NN within a radius, radiance
  estimate = Σ power · BRDF / (π r²).
- **Reference impl (license-clean):** PBRT-v4 `src/pbrt/cpu/integrators.cpp`
  (SPPM) + `kdtree` (Apache-2.0/BSD); pbrt-v3 `photonmap` chapter. Port the
  kd-tree build + k-NN query; cite file:line.

## Chunks

1. `Photon` struct + a balanced **kd-tree** (build O(n log n), query k-NN) in a
   new header `include/astroray/photon/photon_map.h`. Hero-λ XYZ power carry (the
   dielectric already produces hero-λ dispersion — reuse).
2. Rewire `light_tracer_caustic` to deposit into the kd-tree instead of the 2D
   grid; gather = k-NN density estimate at the floor hit (replaces bilinear grid
   gather). Keep the 2-face emission unchanged for now.
3. Unit test: build/query correctness (synthetic photons, known density) +
   end-to-end regression — the `prism-bk7-collimated` scene still passes its
   gates (hue_spread ≥ 0.7, bright_coverage ≥ 0.5) with the kd-tree backend.

## Acceptance

- [ ] `photon_map.h` kd-tree: unit-tested build + k-NN query (CPU, CI).
- [ ] `prism-bk7-collimated` reproduces the rainbow band via the kd-tree backend
      (no visual/gate regression vs pkg106).
- [ ] Cite Jensen 1996 + the PBRT kd-tree file:line in the ported code.

## Non-goals

- Not BSDF-driven photon bouncing (that's pkg110) — keep the 2-face emission.
- Not the camera-side general gather into the default path (pkg111).
- Not GPU. Not progressive/SPPM (a later package). GPU port + CPU/GPU parity is the
  separate follow-up **pkg113** (`.astroray_plan/docs/cpu-gpu-parity-status.md`).
