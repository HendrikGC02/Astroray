# pkg226 — runSMSAttempt receiver-cosine double-count + biased seed-area weight

**Pillar:** 3 (light transport / caustics)
**Track:** A (correctness; render-level caustic gates)
**Status:** open — filed 2026-09-04 as a finding surfaced while implementing pkg127
**Estimated effort:** S–M (one weight expression + a re-bless; the risk is
touching the fleet-blessed caustic references)
**Depends on:** independent of pkg127 (pkg127 already sidesteps this by using the
correct MNEE weight on its deterministic sphere path).

---

## The bug (two coupled issues in the single-vertex Newton SMS path)

`include/astroray/manifold/sms_attempt.h::runSMSAttempt` (the DEFAULT,
non-pkg127 sphere caustic path used by `spectral_path_tracer` and
`sms_caustic_path_tracer` when `sms_specular_poly` is off):

1. **Receiver cosine double-count.** `evalSpectral` already includes the receiver
   cosine — `plugins/materials/lambertian.cpp` returns `albedo * cosTheta / pi`
   (and the other diffuse materials likewise). But `runSMSAttempt` then multiplies
   the geometry factor `G` by `cosX0 = x0Rec.normal.dot(wi_x0)` a SECOND time
   (`sms_attempt.h`, the `G = cosX0 * cosLight / (dist^2 dist^2)` line). The
   receiver radiance therefore carries `cos^2` instead of `cos`.

2. **Biased seed-area weight.** The per-solution weight uses the stochastic
   seed-sampling pdf reciprocal `seedAreaWeight = pi*r^2 / cosSeed` (Zeltner 2020
   biased-SMS variant). Measured against the physically-correct MNEE
   generalized-geometry term (`chainGeometryTerm`, used by the validated
   `runMeshSMSAttempt`), the single-vertex estimator over-brightens the caustic:
   on `sms-refractive-glass-sphere` at 1024 spp the **focus/peak matches** (linear
   ROI max 8.93 vs 8.37) but the **total ROI energy is ~1.5x** the MNEE value.

The two compound; the net is an over-bright caustic with a `cos^2` receiver
falloff. Contrast with `runMeshSMSAttempt` (prism), which uses the correct MNEE
term and no extra receiver cosine.

## Why it matters

The 2026-05-27 `sms-refractive-glass-sphere` reference was a render of this
biased path, so it encoded the bug. pkg127 re-blessed THAT scene to the correct
MNEE-weighted deterministic poly path (2026-09-04). But the **default Newton
path is still shipping the bug** for any sphere caustic when the poly flag is
off — and no reference now guards it.

## Fix plan

- Drop the extra `cosX0` factor from `runSMSAttempt`'s `G` (rely on
  `evalSpectral`'s cosine), matching `runMeshSMSAttempt`.
- Replace `seedAreaWeight` with the MNEE `chainGeometryTerm` (N=1 sphere vertex,
  analytic partials dp=r*tangent / dn=tangent) — the exact weight pkg127's
  `runSMSAttemptPoly` already uses. This makes the Newton and poly paths agree.
- Re-verify: the Newton path should then match the pkg127-blessed
  `sms-refractive-glass-sphere` reference (poly and Newton converge to the same
  caustic). Re-run the caustic regression suite
  (`test_sms_caustic_validation`, `test_sms_caustic_spectral`,
  `test_pkg64_phase3_*`) and re-bless any reference that shifts, with a note.
- Consider whether the prism references need any adjustment (they used the
  correct weight already, so likely not).

## Acceptance

- [ ] `runSMSAttempt` applies the receiver cosine once and uses the MNEE weight.
- [ ] Newton and poly (`sms_specular_poly` on/off) produce matching caustic
      brightness on `sms-refractive-glass-sphere` (SSIM ≥ 0.98 between them).
- [ ] Caustic regression suite green; any re-blessed reference documented.

## Provenance

Surfaced 2026-09-04 during pkg127 (Specular Polynomials) implementation; see
`.astroray_plan/docs/pkg127-specular-polynomials-research.md` §7.5. pkg127 itself
is unaffected — it uses the correct MNEE weight.
