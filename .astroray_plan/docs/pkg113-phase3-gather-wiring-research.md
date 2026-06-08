# pkg113 Phase 3 — GPU photon-map caustic gather wired into the integrator

Research + design note. Author: package-implementer, 2026-06-09.
Branch: `feat/pkg113-gpu-caustic-gather` (off `feat/pkg113-gpu-photon-emission`).

## What Phase 3 must do (spec §Phase 3 + acceptance table)

1. **Scene-driven emission (a):** before the camera pass, scan the uploaded
   scene for caustic-caster glass and run a forward photon trace to produce a
   `GPhoton` deposit array, then build the Phase-1 hash grid from it — one
   pre-pass per frame, exactly like the CPU `light_tracer_caustic` /
   `spectral_path_tracer` (pkg111) photon pass.
2. **Gather wiring (b):** at receiver (first non-emissive) hits in the GPU
   path-trace kernel, call `photonGridGather` and ADD the caustic irradiance to
   the outgoing radiance, mirroring pkg111's CPU wiring (same radius, same
   `1/(πr²)` density normalization, same Lambertian `albedo·E·scale`).
3. **Acceptance (c):** render `prism-bk7-collimated` + `glass-sphere-caustic` on
   GPU and gate GPU-vs-CPU SSIM ≥ 0.97 + an energy-ratio bound, plus the
   per-scene caustic gates, plus a **mandatory visual PNG check** by the parent.

## Algorithm provenance (CLAUDE.md §6 — no invented math)

Every formula below is a verbatim port of code already in this repo; no new
algorithm is introduced.

| Piece | Source in repo (the canonical math) | Upstream citation |
|---|---|---|
| Forward photon emission/bounce (Snell + Schlick-Fresnel + enter/exit by geometric-normal sign + per-λ Sellmeier + TIR) | `plugins/integrators/spectral_path_tracer.cpp:422-475` (pkg111 general BVH loop); `src/gpu/photon_emission.cu` (Phase 2 device port of the same math) | Arvo 1986 (forward light transport); Schlick 1994 (Fresnel approx); Sellmeier 1871 n(λ) |
| Per-λ CIE deposit weight | `cieCmf1964_10deg` (`data/spectra/cie_cmf.inc`), already mirrored into `photon_emission.cu` `pe_cieCmf` | CIE 1964 10° CMF |
| Hash-grid store + device gather `photonGridGather` | `include/astroray/gpu_photon_store.h` + `src/gpu/photon_store.cu` (Phase 1) | Jensen 2000 §3.1 Eq. 8 density estimate; pbrt-v3 `sppm.cpp` ToGrid/hash (BSD-2-Clause); Teschner 2003 hash primes |
| Gather → radiance wiring (radius calibration, `1/(πr²)`, `albedo·E·scale`) | `plugins/integrators/spectral_path_tracer.cpp:207-221` + `:481-513` (pkg111 CPU wiring) | Jensen 1996 radiance estimate at a diffuse surface |
| Sellmeier device evaluator | `include/astroray/gpu_dispersion.cuh` `gpu_sellmeier_ior` (pkg64-gpu) | Sellmeier 1871; Cycles `closure_principled.h` (Apache-2.0) |

## CPU pkg111 wiring being mirrored (the exact contract)

`spectral_path_tracer.cpp` is the canonical default-path wiring (the spec says
"pkg111 wired this into the default path_tracer — find and mirror"). The two
load-bearing pieces:

**Build (beginFrame / pre-pass), `:339-514`:**
- Union AABB of all `isCausticCaster()` objects → caster centroid + radius.
- Aim a collimated aperture from the sun: `sunDir = (casterC - lightPos).norm()`,
  aperture disc of radius `crad = bboxDiag·0.55` centred `crad+2` upstream.
- General BVH loop per photon: λ ~ U[380,720], refract through transmissive hits
  (`eta = 1/ior` entering / `ior` exiting from `d·ng` sign), accumulate Schlick
  transmittance `tr`, deposit `cmf(λ)·tr·cosθ` on the first diffuse hit after
  `passedCaster`. (cosθ = Lambert cosine, pkg111 addition over pkg106.)
- Build kd-tree, then calibrate:
  - `gatherRadius = 1.5 · median_i( kth-nearest-distance(photon_i, K) )`, K=50.
  - `peak = 95th-percentile irradiance` over a photon subsample.
  - `causticScale = boost / (π · peak)`, boost = 1.2 (folds the Lambertian 1/π).

**Gather (sampleFull), `:207-221`:**
```
if photonMapReady and first hit is non-emissive:
    E = photonMap.estimateIrradiance(point, K=50, gatherRadius)   # = (1/πr²) Σ power
    xyz += albedo · E · causticScale
```
`estimateIrradiance` already divides by `π r²`; `photonGridGather` divides by the
identical `π r²` (`gpu_photon_store.h:170-173`), so the GPU gather returns the
same density estimate and the same `albedo · E · scale` applies.

## Device port decisions

- **GPU material transmissive test.** The CPU loop keys on
  `rec.material->isTransmissive()` + `iorAt(λ)`. On the GPU the uploaded
  `GMaterial` carries `type`, `ior`, `transmission`, `isDispersive`, `dispersion`
  directly (`gpu_types.h:340-370`). A caster glass is `type==GMAT_DIELECTRIC`
  (the test scenes use `create_material("dielectric", …)`), so the device trace
  detects transmission by `mat.type == GMAT_DIELECTRIC` (with a
  `GMAT_CLOSURE_GRAPH` + dielectric-transmission-closure fallback). Per-λ IOR via
  `gpu_sellmeier_ior(mat.dispersion, λ)` when `isDispersive`, else `mat.ior`.
- **Geometric outward normal.** `gpu_bvh_hit` writes the *oriented* `rec.normal`
  (flipped to face the ray) plus `rec.frontFace`. The CPU general loop needs the
  *geometric outward* normal (`ng`) to pick enter/exit. Recover it:
  `ng = frontFace ? rec.normal : -rec.normal` (un-flip). This matches the CPU
  `rec.normal` semantics (the CPU `HitRecord::normal` is the geometric outward
  normal, see `light_tracer_caustic.cpp:297`).
- **Caster scan + aperture aim on the host.** The aperture frame (sun direction,
  caster bounds) is computed on the host in `cuda_renderer.cu` from the same
  `Renderer` the CPU integrator reads (it is already stashed as
  `impl->hostRenderer`), then passed as scalars to the device pre-pass kernel —
  mirroring the CPU `buildPhotonMap` host setup. This keeps the device kernel a
  pure per-photon trace, identical in shape to Phase 2's `kEmitPhotons`.
- **Grid persistence.** Phase 1's `cuda_photon_store_query` builds the grid AND
  downloads results in one shot (parity harness). Phase 3 needs a *persistent*
  device grid the path-trace kernel reads. So Phase 3 adds a `GPhotonGridDevice`
  RAII holder (the same count/scan/scatter build, but the CSR buffers stay
  resident and a `GPhotonGrid` view is handed to the megakernel by value).
- **Radius + scale calibration.** The CPU uses a kd-tree kth-nearest sweep. On
  the GPU we reuse the same *intent* with the hash grid: build the grid at a
  provisional radius from photon density (mean spacing from the AABB volume and
  count, the pbrt `gridRes`-from-diagonal relationship inverted), then estimate
  the 95th-percentile irradiance over a photon subsample (one device gather pass)
  to fix `causticScale = boost/(π·peak)`. Boost = 1.2, identical to pkg111.

## Risk register (RTX-gated — CI is blind, memory ci_has_no_gpu_runtime_blindspot)

- **Salt-and-pepper trap** (memory `general-photon-loop-needs-solid-glass`): the
  numeric caustic gates pass on chromatic noise. The acceptance test writes the
  GPU PNGs to disk and the report demands a parent visual pass. The glass SPHERE
  is a closed solid (good); the prism is flat — pkg113 Phase 2 decided the flat
  prism general loop scatters into noise, so the prism scene on GPU is the higher
  risk. See "deferred / risks" in the final report.
- **Closure-graph glass.** If a test glass lowers to `GMAT_CLOSURE_GRAPH` rather
  than `GMAT_DIELECTRIC`, the device trace must read the dielectric-transmission
  closure's `ior`. Handled with a closure scan fallback.
- **Energy parity vs CPU.** CPU uses 3e6 photons + kd-tree; GPU uses an aperture
  lattice + hash grid. The density estimate is the same `1/(πr²)Σpower`, and the
  scale is recalibrated the same way, so the energy ratio should land within the
  gate, but the photon *count* differs — gate on SSIM + energy-ratio, never on a
  raw photon count (the same tiered-equivalence rule as Phase 1/2).
</content>
</invoke>
