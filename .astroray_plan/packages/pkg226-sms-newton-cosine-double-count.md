# pkg226 — runSMSAttempt receiver-cosine double-count + biased seed-area weight

**Pillar:** 3
**Track:** A
**Status:** done — PR #686, 2026-09-04
**Estimated effort:** S–M (one weight expression + a re-bless; the risk is touching the fleet-blessed caustic references)
**Depends on:** pkg127

---

## Goal

Before: the default single-vertex Newton SMS path (`runSMSAttempt`) double-counted the receiver cosine (receiver radiance carried `cos^2` instead of `cos`) and used a biased seed-area weight, over-brightening the default Newton caustic ~1.5× relative to the MNEE value. After: `runSMSAttempt` applies the receiver cosine once and uses the MNEE `chainGeometryTerm` weight, matching the pkg127 poly path, so the Newton and poly paths converge to the same caustic on `sms-refractive-glass-sphere`.

---

## Context

`include/astroray/manifold/sms_attempt.h::runSMSAttempt` is the DEFAULT, non-pkg127 sphere caustic path used by `spectral_path_tracer` and `sms_caustic_path_tracer` when `sms_specular_poly` is off. This package serves Pillar 3 (light transport / caustics) on Track A (correctness; render-level caustic gates). The 2026-05-27 `sms-refractive-glass-sphere` reference was a render of this biased path, so it encoded the bug; pkg127 re-blessed THAT scene to the correct MNEE-weighted deterministic poly path (2026-09-04). But at filing, the default Newton path was still shipping the bug for any sphere caustic when the poly flag is off — and no reference guarded it — which is why this could not wait. The change is CPU-only. It is independent of pkg127: pkg127 already sidesteps this by using the correct MNEE weight on its deterministic sphere path, and pkg127 itself is unaffected — it uses the correct MNEE weight.

---

## Evidence

- 2026-09-04: surfaced during pkg127 (Specular Polynomials) implementation.
- 2026-09-04: receiver cosine double-count — `evalSpectral` already includes the receiver cosine (`plugins/materials/lambertian.cpp` returns `albedo * cosTheta / pi`, and the other diffuse materials likewise), but `runSMSAttempt` then multiplied the geometry factor `G` by `cosX0 = x0Rec.normal.dot(wi_x0)` a SECOND time (`sms_attempt.h`, the `G = cosX0 * cosLight / (dist^2 dist^2)` line). The receiver radiance therefore carried `cos^2` instead of `cos`.
- 2026-09-04: biased seed-area weight — the per-solution weight used the stochastic seed-sampling pdf reciprocal `seedAreaWeight = pi*r^2 / cosSeed` (Zeltner 2020 biased-SMS variant). Measured against the physically-correct MNEE generalized-geometry term (`chainGeometryTerm`, used by the validated `runMeshSMSAttempt`), the single-vertex estimator over-brightens the caustic: on `sms-refractive-glass-sphere` at 1024 spp the focus/peak matches (linear ROI max 8.93 vs 8.37) but the total ROI energy is ~1.5× the MNEE value.
- 2026-09-04: the two compound; the net is an over-bright caustic with a `cos^2` receiver falloff. Contrast: `runMeshSMSAttempt` (prism) uses the correct MNEE term and no extra receiver cosine.
- 2026-09-04: the 2026-05-27 `sms-refractive-glass-sphere` reference was a render of this biased path, so it encoded the bug.
- 2026-09-04: LANDED (PR #686) — `runSMSAttempt` now uses the MNEE `chainGeometryTerm` weight (no cos² double-count, no biased seed-area pdf), matching the pkg127 poly path; the over-bright (~1.5×) default Newton caustic is corrected.
- 2026-09-04: measured Newton-vs-poly SSIM 0.987, mean ratio ~0.95 (residual ~5% underestimate at multi-solution foci is inherent to stochastic single-seed Newton — the exact result is the poly path).
- 2026-09-04: the `sms_caustic_validation` PSNR gate was recalibrated 5.0 → 2.5 dB (the de-brightened caustic sits closer to the caustic-free baseline; the larger old gain encoded the bug).
- 2026-09-04: CPU-only change.

---

## Reference

- Research: `.astroray_plan/docs/pkg127-specular-polynomials-research.md` §7.5 (where this was surfaced during pkg127).
- Code: `include/astroray/manifold/sms_attempt.h` (`runSMSAttempt`, `runMeshSMSAttempt`, pkg127's `runSMSAttemptPoly`); `plugins/materials/lambertian.cpp`.
- External: Zeltner 2020 (biased-SMS variant).

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/manifold/sms_attempt.h` | `runSMSAttempt`: drop the extra `cosX0` receiver-cosine factor from `G` and replace `seedAreaWeight` with the MNEE `chainGeometryTerm` weight. |

### Key design decisions

- Drop the extra `cosX0` factor from `runSMSAttempt`'s `G` (rely on `evalSpectral`'s cosine), matching `runMeshSMSAttempt`.
- Replace `seedAreaWeight` with the MNEE `chainGeometryTerm` (N=1 sphere vertex, analytic partials dp=r*tangent / dn=tangent) — the exact weight pkg127's `runSMSAttemptPoly` already uses. This makes the Newton and poly paths agree.
- Re-verify: the Newton path should then match the pkg127-blessed `sms-refractive-glass-sphere` reference (poly and Newton converge to the same caustic). Re-run the caustic regression suite (`test_sms_caustic_validation`, `test_sms_caustic_spectral`, `test_pkg64_phase3_*`) and re-bless any reference that shifts, with a note.
- Consider whether the prism references need any adjustment (they used the correct weight already, so likely not).

---

## Acceptance criteria

- [x] `runSMSAttempt` applies the receiver cosine once and uses the MNEE weight.
- [x] Newton and poly (`sms_specular_poly` on/off) produce matching caustic brightness on `sms-refractive-glass-sphere` (SSIM ≥ 0.98 between them).
- [x] Caustic regression suite green; any re-blessed reference documented.

---

## Non-goals

- Do not adjust the prism references — they used the correct weight already, so likely no adjustment is needed.
- Do not expect the stochastic single-seed Newton path to remove the residual ~5% underestimate at multi-solution foci — it is inherent to the estimator; the exact result is the poly path.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)
