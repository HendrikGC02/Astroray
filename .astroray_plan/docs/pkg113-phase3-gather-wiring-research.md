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

---

## FOLLOW-UP FIX PLAN (RTX-checked 2026-06-09 — wiring builds + fires, 2 issues)

The Phase-3 wiring is complete and the gather fires (GPU glass-sphere peak luminance
~0.39), but RTX verification surfaced two issues. Both are fully root-caused below; this
is a self-contained follow-up task.

### Issue 1 — SMS regression (test_pkg64_gpu_phase3_prism_receiver_energy)
**Root cause:** the pre-pass is gated on `use_refractive_caustics && hostRenderer && a
caustic-caster exists` (`cuda_renderer.cu` render + renderMultiwavelength, ~l.101/147),
and on success sets `useCaustics=false` to disable legacy SMS-GPU (no double-count). But
the pkg64-gpu SMS test sets the **identical** trigger (`use_refractive_caustics=True` +
`set_object_caustic_caster(True)`), so the photon pre-pass takes over and disables the SMS
path the test measures → receiver energy collapses.
**Fix (transition-clean):** gate the photon pre-pass on a NEW opt-in flag
`use_photon_caustics` (default false), distinct from `use_refractive_caustics`. The
glass-sphere Phase-3 test opts in; the pkg64-gpu SMS test (no opt-in) keeps SMS. Add
`use_photon_caustics_` + `setUsePhotonCaustics` to the Renderer + a pybind setter, gate the
two `cuda_renderer.cu` call sites on it. (Once the photon path is fully validated, the owner
flips the default to photon-map and retires SMS per parity-doc Decisions §1 — but that is a
separate owner step, NOT this fix.)

### Issue 2 — calibration over-diffuses (caustic-ROI energy ~433x CPU)
**Root cause:** the gather radius (`photon_caustic.cu` ~l.345-364) is set from a GLOBAL
deposit-AABB mean-spacing `sqrt(area/n)`, which outlier deposits (grazing/TIR strays) inflate
→ radius too large → the caustic over-smooths → `peak95` (the calibration percentile) too
small → `causticScale = boost/(π·peak95)` too large → total ROI energy ~433x the CPU's tight
kNN speck (visual confirmed: soft over-bright blob vs CPU tight spot).
**Fix:** make the radius LOCAL/robust like the CPU 1.5·median-kth-nearest — either (a) a
percentile deposit-AABB (clip the outer ~5% of deposits before computing area), or (b) a true
per-receiver k-NN radius on the hash grid. Re-measure the ROI ratio (target [0.4,2.5]) + the
visual (a focused spot).

### Issue 3 — acceptance scene renders near-black on BOTH backends
The `glass-sphere` test scene is caustic-only (no direct floor lighting), so CPU and GPU both
render near-black (CPU ROI energy 0.71) — a poor parity target. **Add direct floor lighting**
(NEE to the sun on the lambertian floor) so there is a clear bright caustic on a lit floor to
calibrate against and to eyeball. Then un-xfail `test_gpu_glass_sphere_caustic_parity`.

### Gate note (settled by precedent, not a new decision)
The spec's literal SSIM≥0.97 is unreachable for independent MC camera streams (memory
`ssim-wrong-gate-for-independent-rng`; pkg64-gpu retired the identical gate, #419). The test
already gates PRIMARILY on the robust caustic-ROI energy parity + the mandatory visual PNG,
with SSIM as a secondary 0.80 floor — consistent with the pkg64-gpu resolution.

---

## UPDATE 2026-06-09 — polish pass: 2 fixes LANDED, root cause of the 433x COMPLETE

Ran the workflow-designed polish (understand→design→adversarial-verify; the critique caught
two would-be defects: a floor-fill that defeats the ROI gate, and Design-A global-density
proxy ≠ the CPU local kNN). Implemented the corrected plan:

**LANDED + verified:**
1. **SMS regression FIXED.** New opt-in `usePhotonCaustics` Renderer flag (default false) gates
   the pre-pass in both `cuda_renderer.cu` sites; the pkg64-gpu SMS test (no opt-in) keeps SMS.
   `test_pkg64_gpu_phase3_prism_receiver_energy` PASSES again; 60 GPU tests pass, 0 regressions.
2. **Radius now CPU-faithful.** Replaced the global-AABB mean-spacing with the CPU's exact
   `1.5*median(k-th-nearest)` via a new `kKthNearest` device kernel + a two-pass build
   (provisional grid → measure kth-nearest → rebuild tight). Radius 0.044 → 0.015.

**The 433x is NOT the radius (it is ROI-INVARIANT under peak95 auto-scale).** CAUSTIC_DBG
(env-gated, kept) shows: n=791530 deposits, depositExt=(7,0,6), **rmsXZ=0.83**, peak95≈2.1e5,
scale≈1.8e-6. The CPU and GPU **aperture, emission loop, and geometric-normal handling are
byte-identical** (verified: crad, origin0, sunDir, the refract/passedCaster/deposit loop, and
the GPU's `frontFace?normal:-normal` recovery all match the CPU). Both produce the same caustic
core + aberration skirt.

**THE root cause = the density ESTIMATOR.** CPU `estimateIrradiance` (`photon_map.h:89-108`) is
an **adaptive k-NN + Jensen cone filter**: the effective radius is the k-th-nearest distance AT
EACH QUERY POINT (`r2 = heap.front()`), so it SHRINKS in the dense focal core → a SHARP bright
peak; the cone weight `1 - sqrt(d)/(kf·r)` further sharpens. The GPU `photonGridGather`
(`gpu_photon_store.h`) is **fixed-radius, no cone filter** → the core is over-smoothed → flat
peak → peak95 too small → `causticScale = boost/(π·peak95)` too large → the (real, shared)
aberration skirt rises above the ROI's 0.01 floor → ROI ~430x the CPU's tight speck.

**FIX (the focused next task):** add a SEPARATE adaptive k-NN cone gather for the caustic path
— mirror `estimateIrradiance` exactly (find K nearest in the 27-cell neighbourhood like
`kKthNearest`, use the k-th distance as the local radius, cone-weight `kf=1.1`, normalize by
`(1 - 2/(3kf))·π·r²`). Use it in (a) `kPeakGather` calibration and (b) the megakernel receiver
gather. KEEP the fixed-radius `photonGridGather` for the phase-1 store unit test (which pins
it). Perf: the gather is per-receiver-pixel in the hot megakernel, so the bounded-K max-array
(K=50) cost matters — profile. Then the ROI ratio should land in [0.4,2.5] and the PNG show a
sharp caustic; un-xfail `test_gpu_glass_sphere_caustic_parity`.

---

## UPDATE 2026-06-09 (cont.) — adaptive gather LANDED; remaining issue is the DEPOSITS, not the gather

Implemented the adaptive k-NN cone gather (`photonGridGatherKnn` in gpu_photon_store.h, mirroring
`estimateIrradiance` exactly: k-th-nearest = local radius, Jensen cone weight kf=1.1, cone-norm)
and wired it into both megakernels + `kPeakGather` (phase-1's fixed `photonGridGather` kept for
its pinned unit test). **It did NOT change the ROI (428x) or peak95 (~212K).** So the gather was
NOT the dominant cause — the deposits themselves lack the CPU's sharp core.

**DECISIVE direct comparison (CAUSTIC_DBG on both backends, same scene):**
| | n | centroidXZ | **rmsXZ** | totalY |
|---|---|---|---|---|
| GPU | 791530 | (0.649, 0.003) | **0.8323** | 184222 |
| CPU | 648455 | (0.712, 0.003) | **0.1495** | 175944 |

Same total energy, similar count + centroid, but **the GPU caustic deposits are 5.6x more SPREAD**
(rmsXZ 0.83 vs 0.15; GPU depositExt spans the whole 7x6 floor — wide-angle exit outliers the CPU
does not have). So the GPU caustic genuinely does not focus like the CPU's.

**This is NOT the gather, calibration, or wiring — it is the EMISSION deposit distribution.** And
the emission CODE is byte-identical: verified `pc_refract` == CPU `refract` (spectral_path_tracer.cpp:588
== photon_caustic.cu:90, identical Snell), `pc_iorAt`→1.5 for the dielectric, the geometric-normal
recovery (`frontFace?n:-n`) == CPU `rec.normal`, the aperture (crad/origin0/sunDir), maxDepth, and
the TIR-reflect fallback all match. So the divergence is in **the GPU sphere INTERSECTION numerics**
(`gpu_bvh_hit` entry/exit point + normal precision at/near the rim) **or the jittered-lattice vs
random aperture sampling** producing wide-angle exit strays.

**NEXT (focused diagnostic):** trace the SAME aperture point through both emitters and log each
hit point + normal + refracted direction at the sphere entry and exit; find the bounce where the
GPU exit direction diverges from the CPU. Prime suspects: (1) the GPU sphere-exit intersection
(ray origin INSIDE the sphere — does `gpu_bvh_hit` pick the correct far root + outward normal?),
(2) grazing-rim precision. Once the deposits match (rmsXZ ~0.15), the adaptive gather + the
CPU-median radius already in place should put the ROI in band. The SMS-regression fix + the
adaptive gather + the CPU-median radius are correct and stay.
