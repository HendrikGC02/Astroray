# pkg106 — SMS Chromatic Caustics on Triangulated Prisms

**Pillar:** 2 (Spectral core) + 3 (Light transport)
**Track:** A (CPU integrator + numerical work) + C (research)
**Status:** in progress (Chunk A done PR #387, 2026-05-28 — analytic Jacobian; Chunks B-E remain)
**Estimated effort:** 1–2 weeks investigation, then either 2–4 weeks port-and-validate or 1 week deferral note
**Depends on:** pkg64-gpu Phase 1/2/3 (done) + pkg64-gpu-sellmeier-session2-multi-ior (filed)

---

## Goal

**Before:** SMS Newton (Zeltner 2020 + Hanika 2015 per-wavelength residual)
converges efficiently on analytic surfaces (spheres, planes). On
triangulated geometry (e.g. an equilateral glass prism authored as 8
triangles), the Newton iteration does not converge reliably because the
piecewise-flat manifold has discontinuous normals at every shared edge.
The chromatic signal that does arrive at the receiver in such scenes is
unbiased but extremely high-variance — at 4096 spp the rendered image
on the receiver is a salt-and-pepper RGB noise field rather than a clean
rainbow band, despite the `hue_spread` metric correctly registering it
as "highly chromatic."

**Verified during pkg104 (2026-05-27)** by attempting a classic triangular-
prism dispersion scene: equilateral BK7 prism + collimated sun + opaque
baffle + flat-screen receiver, rendered with `sms_caustic_path_tracer` +
`spectral_newton=1`. Chromatic noise was visible on the receiver but no
discernible rainbow band. The pkg104 BK7 scene fell back to a sphere
(acting as a lens), which works but is not visually a "prism rainbow."

**After:** SMS finds the per-wavelength refraction manifold through a
triangulated prism well enough that a 1024-spp render at 384×256 shows
a visible rainbow band on a receiver positioned 2–3 prism-lengths away.

---

## Context

Three plausible approaches, each with literature precedent:

1. **Smoothed-normal SMS.** Treat the prism's piecewise-flat surface as a
   smooth manifold by interpolating normals at vertices (Phong-style)
   for the Newton residual specifically, even though the actual ray-
   surface intersection still uses the flat normal. The Newton sees a
   smooth gradient; the radiance evaluation sees the geometry. PBRT-v4
   does something similar for `TriangleMesh` shading vs intersection.
   *Risk:* the Newton may converge to a point that isn't actually on
   the discrete surface, producing biased estimates.

2. **MNEE (Manifold Next-Event Estimation) — Hanika 2015 §3.** A
   different family of caustic estimators that works by tracing a
   chord-deformation path from sender to receiver and iterating to
   satisfy Snell at each vertex. Implemented in Cycles as
   `kernel/integrator/mnee.h` (Apache-2.0). MNEE is more naturally
   triangle-friendly because it operates on chord-vertices, not on
   manifold-position derivatives. The trade-off is that MNEE doesn't
   handle reflective caustics; we'd need to keep SMS for the reflective
   branch (the cup scene) and add MNEE for the refractive prism branch.

3. **Defer.** Accept the sphere-as-lens scene as the chromatic-dispersion
   regression target and document the prism gap as "no canonical
   reference renderer implements rainbow prisms efficiently on
   triangles either — Cycles' MNEE is closest but still produces noisy
   prism caustics at sub-1k spp."

---

## Recommendation

Investigate (1) and (2) in parallel — both are 1–2 days of reading. Then
pick one based on:
- If (1) shows convergence in toy 2D Newton tests with smoothed normals,
  prototype the integration ahead of (2) since it stays inside the
  existing SMS code path.
- If (1) doesn't converge, port Cycles' MNEE as a sibling integrator
  (`mnee_caustic_path_tracer`) and route the refractive prism path to
  it; keep `sms_caustic_path_tracer` for reflective.

---

## Acceptance criteria

- [ ] Rendered prism-bk7 scene at 1024 spp (≤ 30 s CPU) shows a visible
      rainbow band on the receiver, distinguishable from MC noise
      (`hue_spread > 0.6` AND a continuous rainbow region detected by a
      morphological check, not isolated chromatic pixels).
- [ ] Existing sphere-as-lens scene still passes after the integrator
      change (no regression on chromatic caustic via lens topology).
- [ ] Reflective cup scene still passes.
- [ ] Cited reference: Cycles `kernel/integrator/mnee.h` Apache-2.0 if
      MNEE port; or Phong-style smoothed-normal manifold reference
      (Bauer et al. 2022 "Differentiable Rendering on Triangulated
      Surfaces" or equivalent) if approach (1).

---

## Non-goals

- Not GPU. CPU-only investigation first; GPU port follows pkg55-B' completion.
- Not a new caustic estimator family (PMNEE, etc.) — pick from the two
  approaches above.
- Not animation / time-varying prisms.

---

## Progress

- [x] Spec drafted 2026-05-27 (this file).
- [ ] Phase 1: 1–2 day literature read + toy Newton convergence test.
- [ ] Phase 2: Pick approach, implement.
- [ ] Phase 3: Validate against pkg104 prism-bk7 scene.

---

## Lessons

*(Fill in after the package is done.)*
