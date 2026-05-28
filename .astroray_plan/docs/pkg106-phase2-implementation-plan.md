# pkg106 Phase 2 — Implementation plan (2026-05-28)

Per the 2026-05-28 research note (`pkg106-research-2026-05-28.md`), Phase 2
ports Cycles MNEE for triangulated prism caustics. The full port is
~1-2 weeks; this document breaks it into landable chunks so the work
ships incrementally rather than as one giant PR.

## Source-of-truth

Cycles `src/kernel/integrator/mnee.h` (Apache-2.0). Every ported function
should cite the Cycles file + line range it mirrors per CLAUDE.md §6.

## Five landable chunks

### Chunk A — Port `ManifoldVertex` + half-vector math (~3 days)

**Lands as:** `include/astroray/mnee.h` (new file).

**Contents:**
- `ManifoldVertex` struct (position, tangent frame, normal, eta).
- `compute_half_vector()`, `compute_half_vector_derivatives()` helpers —
  mirrors Cycles `mnee_compute_constraint_derivatives()` lines 646-731.
- Unit tests for the half-vector math against a hand-computed 2D Snell
  example (refraction through a single tilted plane).

**Acceptance:**
- New tests pass (constraint math agrees with analytic Snell).
- No integrator-side change yet; builds clean.
- Other tests untouched.

### Chunk B — Port Newton solver (~3 days)

**Lands as:** extends `mnee.h` + new `tests/test_mnee_newton_convergence.py`.

**Contents:**
- `mnee_newton_solve()` — Cycles lines 824-903 (the manifold walk loop).
- Step-size `beta` adaptation + threshold-based exit.
- Unit tests on a 2-vertex toy chain: light → flat refractor → receiver,
  with a known analytic solution. Assert convergence in ≤8 iterations.

**Acceptance:**
- Toy 2D Newton converges to the analytic Snell-law solution at
  machine precision.
- No real-scene rendering yet.

### Chunk C — Seed-ray construction + caustic-caster detection (~2 days)

**Lands as:** extends `mnee.h` + small touch to `Hittable` interface.

**Contents:**
- `mnee_construct_seed_ray()` — Cycles lines 29-44.
- Reuse existing `Hittable::isCausticCaster()` flag (pkg29a).
- Unit test on a fixed scene (sphere + plane caustic chain) that the
  seed ray's intersection list matches a hand-traced expectation.

### Chunk D — Integrator plugin + wiring (~2 days)

**Lands as:** new `plugins/integrators/mnee_caustic_path_tracer.cpp`,
register via `ASTRORAY_REGISTER_INTEGRATOR("mnee_caustic_path_tracer", …)`.

**Contents:**
- The plugin invokes A/B/C on each path vertex that hits a caustic-
  flagged object during NEE.
- Stays single-wavelength per ray (the existing CPU dielectric's hero-
  wavelength + `terminateSecondary()` infrastructure handles dispersion).
- Cornell-box parity test: render the simple sphere-caustic scene with
  both the existing `sms_caustic_path_tracer` and the new
  `mnee_caustic_path_tracer`; assert SSIM ≥ 0.95 between them
  (different algorithms, similar visual result).

### Chunk E — pkg104 prism scene + acceptance (~2 days)

**Lands as:** pkg104 `prism-bk7-collimated/scene.py` switches to a true
triangulated prism + `mnee_caustic_path_tracer` integrator; new gates
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
