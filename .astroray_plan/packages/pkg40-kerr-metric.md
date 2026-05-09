# pkg40 — Kerr Metric Plugin

**Pillar:** 4  
**Track:** A  
**Status:** done
**Estimated effort:** 3 sessions (~9 h)  
**Depends on:** pkg04 (done), PR #119 (merged), pkg34 (backend capability guardrails recommended before GPU parity claims)

**Reference research:** `.astroray_plan/docs/kerr-metric-research.md`
(metric components, Christoffel symbols, analytic test values, and license notes
— read this before writing any metric code)

---

## Reference Implementations

All metric math comes from Bardeen, Press & Teukolsky 1972 (ApJ 178, 347;
DOI 10.1086/151796). The repos below are cross-validation references.

| Repo | Commit | License | Mirror permitted | Files to study |
|------|--------|---------|-----------------|----------------|
| [RAPTOR](https://github.com/tbronzwaer/raptor) (Bronzwaer et al. 2018, A&A 613 A2) | `08cb9a2` | **GPLv3** | **No** — cross-validation only | `metric.c` (BL metric + Christoffel), `integrator.c` (RK4 geodesic driver) |
| [ipole](https://github.com/AFD-Illinois/ipole) (Mościbrodzka & Gammie 2018, MNRAS 475 43) | `7f7a482` | BSD-3-Clause | Yes — cite file + commit in code | `src/geodesics.c` (2nd-order symplectic), `src/geometry.c` (BL metric) |
| [GYOTO](https://github.com/gyoto/Gyoto) (Vincent et al. 2011, CQG 28 225011) | — | CeCILL (GPL-incompat) | **No** — numerical cross-check only | — |

**Do not mirror any RAPTOR code.** Its GPLv3 license is incompatible with
Astroray's license regardless of how selectively the code is adapted.
The metric formulae are mathematical results in the public domain (BPT 1972);
RAPTOR's code representation of them is not what we borrow.

---

## Goal

**Before:** The `BlackHole` shape plugin hard-codes Schwarzschild
geodesic integration inline. There is no abstract metric interface;
adding a second metric (Kerr) would require duplicating the entire
integration loop. The GR integrator uses `float` precision, which is
known to cause numerical instability near coordinate singularities in
Boyer-Lindquist coordinates.

**After:** A `GRMetric` abstract base class defines the geodesic
derivative and horizon-crossing interface. `SchwarzschildMetric` is
extracted from the existing code with no behavioural change.
`KerrMetric` implements the Hamiltonian formulation in Boyer-Lindquist
coordinates at `double` precision. The `BlackHole` shape plugin
selects its metric from `MetricRegistry` by name. Existing
Schwarzschild renders are pixel-identical.

---

## Context

This is the gating package for Pillar 4. Every astrophysics plugin
that follows — accretion models, synchrotron jets, lensing — depends
on a working Kerr geodesic integrator. The Schwarzschild code is
validated and stable; extracting it cleanly is the first step.

Kerr geodesics are the physics that make Astroray's astrophysical
visualization unique: frame-dragging, ergosphere effects, and
spin-dependent photon ring structure are all inaccessible without
them.

---

## Reference

- **Research notes (read first):** `.astroray_plan/docs/kerr-metric-research.md`
  (metric formulae, Christoffel symbols, analytic test values, license status)
- Design doc: `.astroray_plan/docs/astrophysics.md §4.1`
- External references: `.astroray_plan/docs/external-references.md §4`
- Existing BlackHole plugin: `plugins/shapes/black_hole.cpp`
- MetricRegistry hook: present in `include/astroray/register.h`
- Schwarzschild regression reference: `tests/reference/schwarzschild_baseline_256.png`
- Key papers: Bardeen, Press & Teukolsky 1972 (BPT; ISCO + photon sphere),
  Dexter & Agol 2009 (geokerr), Chan et al. 2013 (GRay),
  Cárdenas-Avendaño et al. 2022 (photon ring analytic)
- Cross-check tools: RAPTOR (GPLv3 — reference only), GYOTO (CeCILL — reference only),
  ipole (BSD-3 — selective mirror permitted; commit 7f7a482)

---

## Prerequisites

- [x] pkg04 is done and the `MetricRegistry` typedef exists in
      `register.h` (or equivalent).
- [ ] PR #119 (native spectral GR disk emission) is merged and the
      spectral GR dispatch path is stable.
- [x] Save a pre-refactor Schwarzschild reference render before touching
      the black-hole/metric implementation.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/gr_metric.h` | `GRMetric` abstract base class, `GeodesicState` struct, `MetricRegistry` macro. |
| `plugins/metrics/schwarzschild.cpp` | `SchwarzschildMetric` — extracted from existing `black_hole.cpp` code. Single-file plugin with `ASTRORAY_REGISTER_METRIC`. |
| `plugins/metrics/kerr.cpp` | `KerrMetric` — Hamiltonian formulation in Boyer-Lindquist. Double-precision integrator. |
| `tests/test_gr_metrics.py` | Unit and integration tests for both metrics. |
| `tests/reference/schwarzschild_baseline_256.png` | Existing Schwarzschild render reference captured before the refactor. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/shapes/black_hole.cpp` | Remove inline Schwarzschild integration. Construct metric from `MetricRegistry` using `ParamDict` `"metric"` key (default `"schwarzschild"`). Delegate geodesic integration to the metric object. |
| `include/astroray/register.h` | Confirm `MetricRegistry` typedef and `ASTRORAY_REGISTER_METRIC` macro exist; add if missing. |
| `module/blender_module.cpp` | Expose `"metric"` and `"spin"` parameters on BlackHole objects so Blender users can select Kerr. |
| `blender_addon/__init__.py` | Add `metric_type` EnumProperty (`schwarzschild` / `kerr`) and `spin` FloatProperty (0.0–0.998) to the black hole panel. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg40 in-progress → done; update Pillar 4 percentage. |
| `CHANGELOG.md` | Add pkg40 entry under "Pillar 4 — Astrophysics platform". |

### Key design decisions

1. **GeodesicState is an 8-vector.** Position (t, r, θ, φ) and
   conjugate momenta (p_t, p_r, p_θ, p_φ). Stored as `double[8]`.
   The Hamiltonian formulation uses momenta, not coordinate velocities,
   because the Hamilton equations are first-order and numerically
   better-conditioned.

2. **Double precision for the integrator, float elsewhere.** The
   metric's `derivatives()` and the RK45 stepper operate entirely in
   `double`. Conversion to `float` happens only at the ray-scene
   intersection boundary (hit point, normal). This follows GRay2 and
   EinsteinPy's documented experience with FP32 failures near
   coordinate singularities.

3. **Dormand-Prince RK4(5) with adaptive stepping.** Same algorithm
   class as the existing Schwarzschild integrator, but with proper
   error control: local truncation error estimated from the 4th/5th
   order difference, step size scaled by `0.9 * (tol/err)^0.2`.
   Tolerance `1e-10` (double precision allows this).

4. **Conservation monitoring.** For Kerr: energy E, axial angular
   momentum L_z, and Carter constant Q are conserved along geodesics.
   The integrator computes all three at each step and raises a warning
   (not an error) if relative drift exceeds `1e-6`. This is a
   diagnostic, not a corrector — do not project back onto the
   constraint surface.

5. **r < 2.5M capture threshold.** Hard-won from the validated Python
   implementation. Boyer-Lindquist coordinates become singular at the
   outer horizon r_+ = M + √(M²−a²). The integrator must stop before
   reaching the coordinate singularity, not at it. Use `r < 2.5 * M`
   for Schwarzschild (preserving existing behaviour) and
   `r < r_+ + 0.5 * M` for Kerr (slightly outside the horizon, where
   coordinates are still well-behaved).

6. **Step size scaling near horizon.** `dt_max ∝ Δ(r)` where
   `Δ = r² − 2Mr + a²`. As the ray approaches the horizon, Δ → 0 and
   steps shrink automatically. This prevents the integrator from
   overshooting through the coordinate singularity.

7. **Spin parameter range.** `a/M ∈ [0, 0.998]`. Thorne's bound
   (1974) limits astrophysical spin to ~0.998. Values above this
   cause the inner and outer horizons to merge and the coordinate
   system to degenerate. Clamp on construction; do not accept a ≥ M.

8. **Schwarzschild is Kerr at a=0.** The `SchwarzschildMetric` is a
   separate plugin for clarity, validation, and performance (it avoids
   computing θ-dependent terms that vanish at a=0). But the two must
   agree: a Kerr render at a=0 must be pixel-identical to
   Schwarzschild. This is an acceptance criterion.

---

## Acceptance criteria

- [ ] `GRMetric` base class exists with `derivatives()`,
      `horizonCrossed()`, and `conservedQuantities()` pure virtuals.
- [ ] `metric_registry_names()` returns `["schwarzschild", "kerr"]`.
- [ ] Schwarzschild renders are pixel-identical to pre-pkg40 output
      (regression test with saved reference PNG).
- [ ] Kerr at `a=0` produces pixel-identical output to Schwarzschild
      (same scene, same camera, same samples).
- [ ] Kerr at `a=0.9` renders with visible frame-dragging asymmetry:
      the approaching side of the accretion disk is brighter than the
      receding side, and the photon ring is asymmetric.
- [ ] Conservation monitoring reports E, L_z, Q drift < 1e-6 over a
      full geodesic for 95% of rays in the `a=0.9` test scene.
- [ ] Blender addon exposes metric selection and spin parameter.
- [ ] All existing tests pass (no Schwarzschild regressions).
- [ ] New test file has ≥10 tests covering: metric construction, known
      circular orbit periods, horizon detection, capture threshold,
      conservation drift, a=0 equivalence, and a visual frame-dragging
      check.

### Analytic test values (must reproduce to < 1e-6 relative error)

Source: Bardeen, Press & Teukolsky 1972 (ApJ 178, 347). Full derivation
in `.astroray_plan/docs/kerr-metric-research.md §4`.

**ISCO radius** (innermost stable circular orbit):

| Spin a | r_ISCO prograde | r_ISCO retrograde |
|--------|-----------------|-------------------|
| 0      | 6.000000 M      | 6.000000 M        |
| 0.998 M | 1.237 M        | 8.995 M           |

**Photon sphere radius** (unstable circular photon orbit):

| Spin a | r_ph prograde | r_ph retrograde |
|--------|---------------|-----------------|
| 0      | 3.000000 M    | 3.000000 M      |
| 0.998 M | 1.073 M      | 3.998 M         |

**Frame-dragging angular velocity at the outer horizon:**

```
r_+ = M + sqrt(M² - a²)
Ω_H = a / (r_+² + a²) = a / (2 M r_+)
```

For a = 0.998M:  r_+ = 1.0632 M,  Ω_H ≈ 0.4694 c/M (geometric units G=c=1)

This value sets the scale of the photon-ring asymmetry in frame-dragging tests:
the angular velocity of infalling/co-rotating photons near the horizon is Ω_H.

---

## Non-goals

- Do not implement Kerr-Schild coordinates. Boyer-Lindquist first;
  Kerr-Schild is a future optimisation if BL proves too slow on GPU.
- Do not implement accretion disk models here. The existing
  Novikov-Thorne disk is sufficient for visual validation. Slim disk
  and ADAF are pkg42 and pkg43.
- Do not implement ISCO calculation as a standalone function. The
  metric knows its ISCO implicitly; expose it only if a downstream
  package needs it.
- Do not GPU-accelerate the integrator in this package. CPU double-
  precision first; CUDA porting is a separate package after validation.
- Do not add ray-tracing optimisations (early termination, BVH for
  disk intersection). Keep the integration loop clean and correct.

---

## Progress

- [x] Verify MetricRegistry exists in register.h; it already had the typedef
      and `ASTRORAY_REGISTER_METRIC` macro.
- [x] Extend `include/astroray/metric.h` with the pkg40 `christoffel`,
      `inner_product`, and `isFlat()` hooks while preserving the existing
      GR integrator interface.
- [x] Implement `plugins/metrics/kerr.cpp` with Boyer-Lindquist metric
      components, Christoffel symbols, and BPT 1972 analytic quantities.
- [x] Implement `plugins/metrics/schwarzschild.cpp` as a registry wrapper
      that constructs the registered Kerr metric with `a=0`.
- [x] Add `tests/test_kerr_metric.py` analytic gates from BPT 1972.
- [x] Update STATUS.md.

Note: PR #190 tightened pkg40 scope to metric plugins plus analytic gates.
BlackHole delegation, Blender UI, full geodesic validation, and render-level
Kerr asymmetry remain downstream work for pkg41/pkg67.

---

## Lessons

- The live repo already had `Metric`, `GeodesicState`, `MetricRegistry`, and
  the Schwarzschild GR render path. pkg40 therefore kept the old interface
  intact and added the new metric-evaluation hooks as a superset.
- RAPTOR stayed outside the implementation fence: formulas came from the
  BPT 1972 research note, with ipole/RAPTOR used only as documented
  cross-validation references.
- Verification values on 2026-05-10:
  Schwarzschild ISCO `6.000000000000`, Kerr a=0.998 ISCO
  `1.236970655175`, Schwarzschild photon sphere `3.000000000000`,
  Kerr a=0.998 photon sphere `1.073909257680`, horizon angular velocity
  `0.469331702146`.
