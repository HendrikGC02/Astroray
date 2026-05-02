# pkg41 — Kerr Geodesic Validation

**Pillar:** 4  
**Track:** A  
**Status:** open  
**Estimated effort:** 2 sessions (~6 h)  
**Depends on:** pkg40

---

## Goal

**Before:** The Kerr metric from pkg40 renders plausible-looking images
but has not been quantitatively validated against known analytic results
or independent numerical codes. Conservation monitoring exists but there
is no systematic suite of geodesic accuracy tests.

**After:** A validation suite proves the Kerr integrator reproduces
known analytic quantities (ISCO radii, photon ring radii, orbital
periods) to within specified tolerances, and produces images that match
GYOTO reference renders for a set of canonical test configurations.
The validation data and reference images are committed to the repo so
future changes trigger regressions immediately.

---

## Context

Astrophysical visualization is only useful if the physics is right.
Every downstream Pillar 4 package — accretion models, synchrotron
emission, lensing — inherits any error in the geodesic integrator.
This package creates the test infrastructure that protects all of
Pillar 4.

GYOTO is GPL-3 and cannot be linked, but it can be run offline to
produce reference data. The reference images and orbit tables are
committed as test fixtures; GYOTO is not a build or test dependency.

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.1`
- Kerr metric implementation: `plugins/metrics/kerr.cpp` (from pkg40)
- GYOTO: https://github.com/gyoto/Gyoto (GPL-3, cross-check only)
- Analytic references:
  - Bardeen, Press & Teukolsky 1972 — ISCO, photon orbits, frame
    dragging for Kerr
  - Chandrasekhar 1983 — "The Mathematical Theory of Black Holes"
    ch. 7, exact circular orbit formulae
  - Dexter & Agol 2009 — geokerr transfer functions

---

## Prerequisites

- [ ] pkg40 is done: `KerrMetric` and `SchwarzschildMetric` both
      registered and rendering.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/reference/kerr/` | Directory for reference data and images. |
| `tests/reference/kerr/gyoto_a0_256.png` | GYOTO reference: Schwarzschild (a=0), thin disk, 256×256. |
| `tests/reference/kerr/gyoto_a05_256.png` | GYOTO reference: Kerr a=0.5, thin disk, 256×256. |
| `tests/reference/kerr/gyoto_a09_256.png` | GYOTO reference: Kerr a=0.9, thin disk, 256×256. |
| `tests/reference/kerr/gyoto_a0998_256.png` | GYOTO reference: near-extremal Kerr a=0.998, thin disk, 256×256. |
| `tests/reference/kerr/analytic_orbits.json` | Analytic values: ISCO, photon ring radius, orbital frequency for a = {0, 0.5, 0.9, 0.998}. |
| `tests/test_kerr_validation.py` | Comprehensive validation test suite. |
| `scripts/generate_gyoto_references.py` | Script to regenerate GYOTO reference data (requires GYOTO installed; not run in CI). |

### Files to modify

| File | What changes |
|---|---|
| `.astroray_plan/docs/STATUS.md` | Mark pkg41 done; update Pillar 4 percentage. |

### Test categories

#### A. Analytic orbit tests (no rendering)

These call the metric's `derivatives()` directly and verify the
integrator reproduces known quantities.

| Test | What it checks | Tolerance |
|---|---|---|
| ISCO radius vs spin | r_ISCO(a) matches Bardeen et al. 1972 Table I for a = {0, 0.5, 0.9, 0.998} (prograde and retrograde). | < 0.1% relative |
| Photon ring radius vs spin | r_ph(a) for prograde/retrograde circular photon orbits. | < 0.1% relative |
| Circular orbit period | A geodesic launched at r_ISCO with exact circular-orbit momenta completes one orbit (Δφ = 2π) within 0.1% of the analytic period. | < 0.1% relative |
| Frame-dragging precession | A geodesic at r = 10M in Kerr a=0.9 accumulates the correct Lense-Thirring precession angle over one orbit vs the a=0 baseline. | < 1% relative |
| Conservation over long integration | Integrate a generic geodesic (non-circular, non-equatorial) for 1000M of affine parameter. E, L_z, Q drift must stay below threshold. | < 1e-8 relative |
| Horizon capture | A radially infalling geodesic triggers `horizonCrossed()` before reaching r = r_+ for each spin value. | exact (boolean) |

#### B. Image comparison tests (rendering)

These render a standard scene and compare pixel-by-pixel against
GYOTO references.

| Test | Scene | Comparison method |
|---|---|---|
| Schwarzschild shadow shape | a=0, thin disk at r_ISCO–20M, observer at r=100M inclination 80°. | Shadow boundary contour within 2 pixels of GYOTO reference. |
| Kerr shadow asymmetry | a=0.9, same disk and observer. | Shadow centroid offset and D-shape asymmetry within 5% of GYOTO measurement. |
| Near-extremal photon ring | a=0.998, same setup. | Photon ring visible and narrower than a=0.9 case. Qualitative check + ring width measurement. |
| Spin sweep consistency | Renders at a = {0, 0.3, 0.5, 0.7, 0.9, 0.998}. | Shadow size monotonically decreases with spin (prograde). No rendering artifacts (NaN pixels, black patches). |

#### C. Self-consistency tests

| Test | What it checks |
|---|---|
| Kerr a=0 ≡ Schwarzschild | Pixel-identical renders from both metrics (same scene, same RNG seed). |
| Time-reversal symmetry | A geodesic integrated forward then backward returns to origin within tolerance. |
| Equatorial symmetry | A Kerr render with observer at inclination θ vs π−θ produces a vertically mirrored image (equatorial reflection symmetry of the Kerr metric). |

### Key design decisions

1. **GYOTO references are static fixtures.** They are generated once by
   running `scripts/generate_gyoto_references.py` on a machine with
   GYOTO installed, then committed to the repo. CI never runs GYOTO.
   If references need updating, the script is re-run manually and the
   new PNGs are committed.

2. **Shadow comparison is contour-based, not pixel-MSE.** Black hole
   shadows have sharp boundaries; MSE over the full image is dominated
   by the disk emission model (which may differ between GYOTO and
   Astroray). Instead, extract the shadow boundary contour (threshold
   at 5% of peak brightness) and compare geometry: centroid, area,
   and maximum deviation from the reference contour.

3. **Analytic values are hard-coded in JSON, not computed.** The
   reference file `analytic_orbits.json` contains pre-computed values
   from Bardeen et al. 1972 and Chandrasekhar 1983. The tests compare
   Astroray's computed values against these. This avoids the test
   depending on its own implementation for the expected answer.

4. **Tolerance tiers.** Analytic orbit tests: 0.1% (pure numerics,
   should be near machine precision for double). Image tests: 2–5%
   (rendering involves sampling noise, different emission models).
   Conservation tests: 1e-8 (double precision, long integration).

---

## Acceptance criteria

- [ ] All analytic orbit tests pass at stated tolerances.
- [ ] Shadow contour comparison passes for all four spin values.
- [ ] Kerr a=0 ≡ Schwarzschild pixel-identity test passes.
- [ ] Conservation drift test passes (< 1e-8 over 1000M).
- [ ] Spin sweep produces no NaN pixels or rendering artifacts.
- [ ] Reference images and analytic data committed to
      `tests/reference/kerr/`.
- [ ] `scripts/generate_gyoto_references.py` exists and is documented
      (even if not run in CI).
- [ ] All existing tests pass.
- [ ] Test count increases by ≥15.

---

## Non-goals

- Do not make GYOTO a build dependency. Reference data is static.
- Do not validate accretion disk emission models here. The tests use
  the existing Novikov-Thorne model as-is; emission model accuracy is
  pkg42+ territory.
- Do not add GPU-specific tests. CPU validation is authoritative;
  GPU parity is a future package.
- Do not implement EHT-style visibility/baseline comparison. That is
  research-grade validation beyond Astroray's scope.

---

## Progress

- [ ] Create `tests/reference/kerr/` directory structure.
- [ ] Write `scripts/generate_gyoto_references.py` (can be a stub
      with documentation if GYOTO is not available locally).
- [ ] Compute analytic orbit values and write
      `analytic_orbits.json`.
- [ ] Implement analytic orbit tests (ISCO, photon ring, period,
      frame-dragging, conservation, horizon capture).
- [ ] Implement image comparison tests (shadow contour extraction +
      comparison).
- [ ] Implement self-consistency tests (a=0 equivalence, time-reversal,
      equatorial symmetry).
- [ ] Generate or obtain GYOTO reference images; commit to repo.
- [ ] Full test suite green.
- [ ] Update STATUS.md.

---

## Lessons

*(Fill in after the package is done.)*
