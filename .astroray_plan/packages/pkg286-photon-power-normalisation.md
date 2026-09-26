# pkg286 — Physically normalised photon power for the caustic pre-pass (#914)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h): CPU + GPU + tests
**Depends on:** pkg113, pkg221

---

## Goal

Before: both photon-caustic pre-passes (CPU `spectral_path_tracer::buildPhotonMap`,
`light_tracer_caustic`, GPU `cuda_photon_caustic_build`) scale gathered
irradiance by `causticScale = boost / (π · peak95)`, a display normalisation:
the caustic's brightness is pinned to its own 95th-percentile peak, so it does
not scale with light power, transmittance or caster area, and per-map
averaging (#909) converges to E[scale·E] ≠ scale·E[E]. After: each photon
carries flux Φ_p = Φ_light,aperture / N_emitted (Jensen 2001 §7), the density
estimate is E = Σ Φ_p w_p / (norm · π r²) with no calibration constant,
CPU and GPU agree, and a furnace-style flux test proves the caustic integrates
to E_sun · A_proj · T.

---

## Context

The showcase glass finals (PR #911) and #909's per-round maps exposed that
caustic energy is arbitrary. pkg287 (per-light photon emission) cannot be
built on a scale that depends on the map's shape, and pkg285 Phase 2 cannot
bless prism/sms/glass references until the energy is physical. Owner
2026-09-26: tests calibrated on the old scale are re-pinned in the same PR.

---

## Evidence

- 2026-09-26 (#914): `src/gpu/photon_caustic.cu:548-573` and `spectral_path_tracer.cpp:664-680` calibrate `scale = boost/(π·peak95)`, boost = 1.2.
- 2026-09-26 (#909): per-round photon maps + sparse-radius cap landed; caustic noise ∝ 1/√N (16→256 spp ratio 4.12).
- CPU emitter: 3 000 000 photons over a square aperture of half-width `crad` (`spectral_path_tracer.cpp:503-535`), λ ∝ SPD (pkg221, deposit weight collapses to I = ∫S dλ).

---

## Reference

- Jensen, *Realistic Image Synthesis Using Photon Mapping* (2001) §7.1 (photon power), §7.2 (radiance estimate: L = Σ Φ_p f_r / (π r²)), App. B (cone filter norm 1 − 2/(3k)).
- Jensen 1996, "Global illumination using photon maps" (EGWR).
- pbrt-v3 `src/integrators/sppm.cpp` (BSD-2): photon β = Le · |cos| / (pdfPos · pdfDir · lightPdf), no per-map calibration; flux → radiance divide by N_photons per iteration.
- `.astroray_plan/docs/pkg109-110-111-photon-map-research.md`, `caustics-research.md`.
- `include/astroray/photon_spd.h` (pkg221 SPD weight), `include/astroray/gpu_photon_caustic.h` (`PhotonCausticAim`, `scale`).
- Memory: `gpu-caustic-frozen-lattice-and-spd-blind`, `fix-tests-calibrated-on-broken-engine`.

---

## Prerequisites

- [ ] PR #916 (Batch AB, #909 per-round maps) merged.
- [ ] A baseline build of main for the re-pin attribution.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg286_photon_flux_furnace.py` | Collimated sun through a clear glass slab onto a white Lambertian floor: integrated caustic irradiance over the receiver ROI = E_sun · A_slab,proj · T(η) within 3 % (analytic Fresnel T at normal incidence); doubling sun strength doubles the caustic; CPU/GPU ROI means within 5 %. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/spectral_path_tracer.cpp` | `buildPhotonMap`: Φ_aperture = E_light(λ-integrated via pkg221 I) × A_aperture (square 4·crad² today; disc π·crad² once pkg287 samples a disc); Φ_p = Φ_aperture / photonCount (all launched, not depositors); remove the peak95 block; `photonCausticScale_` = 1/π (Lambertian) only. |
| `plugins/integrators/light_tracer_caustic.cpp` | Same replacement for `causticScale_ = boost_/peak`; `caustic_boost` becomes a documented artistic multiplier (default 1.0). |
| `src/gpu/photon_caustic.cu` | Delete `kPeakGather` calibration; `result.scale = 1/π`; photon weight carries Φ_p; keep the k-NN radius calibration (that is geometry, not energy). |
| `include/astroray/gpu_photon_caustic.h` | `PhotonCausticAim` gains `fluxPerPhoton`; `boost` documented as artistic (default 1.0). |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | `buildCausticAim` computes `fluxPerPhoton` from the aimed light (distant: irradiance × aperture area). |
| `include/astroray/photon/photon_map.h` | `estimateIrradiance` returns Σ Φ_p w_p / (norm · π r²) with the Jensen cone norm; no `scale` argument. |
| `tests/test_gpu_caustic_parity.py` | Re-pin pkg185/pkg220 expectations calibrated on the old scale, each with the attribution line in the commit. |

### Key design decisions

- **Distant light first.** Φ_aperture = E_sun · A_aperture where E_sun is the dedicated distant light's irradiance (the same quantity NEE uses, so caustic and direct light share one radiometric origin). Point/spot/area emission is pkg287; this package keeps the single collimated beam but makes it physical.
- **N_emitted is every launched photon**, including those that miss the caster or are absorbed, so Φ_p is unbiased (Jensen §7.1).
- **Boost stays as an explicit artistic knob**, default 1.0, exposed as before; the addon does not set it.
- **The k-NN gather radius calibration stays**; only the brightness calibration goes. Per-round maps (#909) then average an unbiased estimator.
- **Double-count cull** from #909 (aimed light's paths only) is unchanged; the furnace test uses caustics-only receivers so the path-traced leg is zero.

---

## Acceptance criteria

- [ ] `test_pkg286_photon_flux_furnace.py` passes CPU and GPU: flux within 3 % of analytic, linear in sun strength (ratio 2.00 ± 0.05), CPU/GPU within 5 %.
- [ ] `peak95`/`kPeakGather` no longer exist in the tree.
- [ ] Showcase glass render (`showcase.py render --scene glass`) re-inspected by the lead: caustic under the ball has a plausible brightness relative to the direct sun patch (both scale together when sun strength changes).
- [ ] All re-pinned tests carry an attribution line; no test band widened.
- [ ] Shade kernels REG/STACK unchanged (photon build is a separate kernel).

---

## Non-goals

- No per-light emission geometry (pkg287).
- No change to the gather radius model or the k-NN structure.
- No MNEE/SMS changes.

---

## Progress

- [ ] CPU (`spectral_path_tracer`, `light_tracer_caustic`, `photon_map.h`) + furnace test.
- [ ] GPU (`photon_caustic.cu`, snapshot aim) + parity leg.
- [ ] Re-pins + showcase inspection.

---

## Lessons

*(Fill in after the package is done.)*
