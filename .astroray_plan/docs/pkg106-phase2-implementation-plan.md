# pkg106 Phase 2 — Implementation plan (2026-05-28)

Per the 2026-05-28 research note (`pkg106-research-2026-05-28.md`), Phase 2
brings Cycles-MNEE-quality manifold solving to triangulated prism caustics.

## REVISED 2026-05-28 (afternoon, supervised) — scope correction

A codebase audit (see the research note's afternoon update) found the original
"port a ~1000-line `mnee.h` from scratch" framing was inaccurate. Astroray
**already has**:
- `include/astroray/manifold/half_vector_constraint.h` — generalized
  half-vector (`wi+eta*wo`) + 2D tangent residual (Zeltner 2020 / Hanika 2015).
- `include/astroray/manifold/newton_iterate.h` — the manifold Newton loop,
  but with a **numerical central-difference Jacobian** (its own comment flags
  the analytic Jacobian as the Phase-2/3 upgrade).
- `manifold/sms_attempt.h` + `plugins/integrators/sms_caustic_path_tracer.cpp`.

The SMS-fails-on-triangles failure is specifically that central-difference
Jacobian: ±h tangent steps cross triangle edges into neighbours with different
normals → spurious Jacobian discontinuity → divergence → chromatic noise. The
fix is the **analytic constraint Jacobian** (Cycles `mnee.h` `b` matrix, via
the per-`(u,v)` surface partials `dp_du/dp_dv/dn_du/dn_dv`). We therefore do
NOT add a duplicate `mnee.h`; we extend the existing manifold code.

## Source-of-truth

Cycles `src/kernel/integrator/mnee.h` (Apache-2.0) — `mnee_compute_constraint_derivatives`
lines 248–365 (verbatim core math in the research note). Every ported function
cites the Cycles file + line range per CLAUDE.md §6.

## Five landable chunks (revised)

### Chunk A — Analytic constraint Jacobian + 2D Snell unit test (this PR)

**Lands as:** extends `include/astroray/manifold/half_vector_constraint.h`
(NOT a new `mnee.h` — the half-vector + residual already live there).

**Contents:**
- `halfVectorConstraintJacobian(...)` — the analytic 2×2 Jacobian `db` of the
  tangent residual `(h·s, h·t)` w.r.t. the manifold `(u,v)` offset, given the
  surface partials `dp_du, dp_dv, dn_du, dn_dv`. Mirrors Cycles
  `mnee_compute_constraint_derivatives` lines 285–356 (current-vertex `b`
  block); cite Cycles file:line + Hanika 2015 §5.
- A tiny pybind test-binding (or reuse an existing test surface) so Python can
  evaluate the residual + analytic Jacobian on a supplied geometry.

**Acceptance:**
- New unit test: refraction through a single tilted plane (flat ⇒
  `dn_du=dn_dv=0`). Assert (1) residual ≈ 0 at the analytic Snell solution,
  (2) the analytic Jacobian matches a central-difference Jacobian of the
  existing `halfVectorResidual` to ~1e-3.
- No integrator-side change yet; builds clean; other tests untouched.
- The test supplies `dp_du/dp_dv/dn_du/dn_dv` directly (surface plumbing is
  Chunk B), so Chunk A is self-contained.

### Chunk B — Surface (u,v) partials + wire analytic Jacobian into Newton

**Lands as:** triangle/sphere intersection computes `dp_du/dp_dv/dn_du/dn_dv`
into `HitRecord` (currently it only builds an arbitrary `buildOrthonormalBasis`
tangent frame, not the true surface partials); `newton_iterate.h` gains an
analytic-Jacobian path (replacing the central-difference scaffolding for
caustic casters).

**Contents:**
- Triangle: `dp_du/dp_dv` = edge vectors; `dn_du/dn_dv` from shading-normal
  interpolation (0 for flat). Sphere: analytic tangents/normal derivatives.
- New `tests/test_mnee_newton_convergence.py`: light → flat triangulated
  refractor → receiver; assert the analytic-Jacobian Newton converges in ≤8
  iters where the central-difference one diverges/stalls on the facet.

**Acceptance:** analytic Newton converges on a triangulated refractor to the
Snell solution; the FD path's triangle-edge divergence is gone.

### Chunk C — Caustic-caster seed + triangle reprojection (~2 days)

**Lands as:** extends the manifold reprojection to BVH/triangle ray-cast (the
existing reproject callback is sphere-analytic only); reuse
`Hittable::isCausticCaster()`.

**Contents:**
- Triangle reprojection step for the Newton walk (ray-cast onto the caster
  mesh instead of the analytic sphere hit).
- Unit test: seed + reproject on a fixed sphere+plane chain matches a
  hand-traced expectation.

### Chunk D — Wire into the SMS integrator (~2 days)

**Lands as:** `plugins/integrators/sms_caustic_path_tracer.cpp` uses the
analytic-Jacobian Newton for caustic casters (no NEW integrator needed — the
SMS integrator already exists; the original plan's separate
`mnee_caustic_path_tracer` would duplicate it). If a clean toggle is wanted,
gate analytic-vs-FD behind an integrator param.

**Contents:**
- Stays single-wavelength per ray (existing CPU dielectric hero-wavelength +
  `terminateSecondary()` handles dispersion).
- Cornell-box parity: the analytic-Jacobian SMS reproduces the existing
  sphere-caustic result (regression guard, SSIM ≥ 0.95 vs the FD path on the
  sphere scene where FD already works).

### Chunk E — pkg104 prism scene + acceptance (~2 days)

**Lands as:** pkg104 `prism-bk7-collimated/scene.py` switches to a true
triangulated prism + the analytic-Jacobian `sms_caustic_path_tracer`; new gates
config with `hue_spread ≥ 0.7` in a rainbow ROI.

**Contents:**
- Geometry: equilateral triangulated prism, collimated sun, white
  receiver. Same setup that night-1 tried but couldn't make work
  on the SMS integrator.
- Bless reference image; CI smoke verifies hue_spread on the new path.
- Cycles cross-comparison: render the same scene in Cycles (if Cycles
  can — its MNEE for prisms is also flaky, may need to skip).

## Risks

1. **Triangulated normal discontinuities** — MNEE uses `(u, v)` surface
   parameterisation per face; the constraint solver linearises locally
   so it should be robust, but edge cases (rays grazing a triangle
   edge) need careful handling.
2. **CPU-only initially** — the GPU port is gated on pkg55-B' wavefront
   completion (which is shipping over multiple sessions). Document this
   in chunk D's notes.
3. **Performance** — Cycles MNEE is ~2-3× slower than SMS for the same
   visual result. The pkg104 4096-spp budget already covers it; if a
   future viewport-perf test fails, that's a chunk-F follow-up.

## Decision points (owner)

- **Cite-mirror-borrow vs reimplement-with-citations:** the
  research note assumed cite-mirror-borrow (port Cycles code verbatim
  with per-function citations). This is the cleaner path; reimplement
  is only justified if a license issue surfaces, which it shouldn't
  (Apache-2.0 → MIT compatible).
- **Single-precision vs double-precision Newton:** Cycles uses float
  by default; double if `__KERNEL_USE_DOUBLE__` is set. Astroray's
  CPU is float; the Newton convergence threshold (1e-5) is tolerant.
  Recommend stay single-precision.

## Total estimate

5 chunks × 2-3 days each = **~12-15 days of focused work**, landing as
5 PRs. Each chunk is independently mergeable so the work parallelises
to multiple sessions / assignments.

## Today's deliverable

This plan. The file skeleton is intentionally left as a chunk-A first
step rather than seeded here — landing an empty header without the
constraint math would be lower value than this plan.
