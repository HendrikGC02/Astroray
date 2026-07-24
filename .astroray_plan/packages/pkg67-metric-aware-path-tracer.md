# pkg67 — Metric-Aware Path Tracer (GR + Spectral Unification)

**Pillar:** 4
**Track:** A (research-grade — must do WebSearch + WebFetch literature pass first)
**Status:** done (PR #262 merged 2026-05-14 — Option α) — MinkowskiMetric + `SampledWavelengths::redshift` + `GRSpectralResult::frequencyShift` exposure. See "Realized architecture" below for why the spec's literal wording was not implemented verbatim.
**Estimated effort:** 1 month (~120 h, multiple sessions)
**Depends on:** pkg40 (Kerr metric, open — can run in parallel after Kerr's interface lands)

---

## Goal

**Before:** GR rendering and the standard path tracer are separate code paths. The standalone `gr_integrator` shoots rays through a metric. `path_tracer` (the production integrator) assumes flat space. There is no way to render a scene that mixes a Kerr black hole with normal materials and spectral physics under one renderer.

**After:** `path_tracer` calls a `Metric` virtual to advance rays. Flat Minkowski metric is the default and uses a fast straight-line code path (no virtual call cost in the hot loop). Curved metrics (Schwarzschild, Kerr) plug in via the existing `MetricRegistry` from Pillar 4 prep. Spectral wavelengths along curved geodesics are correctly red-shifted by the metric's tangent-vector inner product. One integrator. Two metrics. Spectral works in both.

---

## Goal (skeptical detail)

The journal-article-grade claim this package enables: *"Astroray supports physically-correct spectral path tracing in arbitrary stationary spacetimes, with flat-space performance preserved by a compile-time fast path."*

If this package does not preserve flat-space performance, the journal article cannot honestly claim Cycles-equivalent GPU speed. So the fast-path requirement is non-negotiable.

---

## Context

You explicitly chose the fast-path approach over the always-virtual approach. The right architecture is what RAPTOR/ipole/GYOTO use: a `Metric` interface returning Christoffel symbols (or a step function), with the integrator either taking a fast straight line in flat space or RK4/RK45-integrating along a null geodesic in curved space. Wavelength is a per-ray scalar that gets multiplied by the redshift factor at each step.

This is the unification work. After it, GR + spectral + GPU + materials all compose. Before it, they're four separate stories.

---

## Reference

- Existing GR work: [include/astroray/metric.h](include/astroray/metric.h), [include/astroray/gr_integrator.h](include/astroray/gr_integrator.h), `MetricRegistry` (added in Pillar 4 prep cleanup).
- **External (must verify with WebSearch before relying on):**
  - Bronzwaer, Davelaar, Younsi, et al., "RAPTOR I/II", A&A 2018 / 2020. Open source (GPLv3); reference for Kerr null-geodesic integrators.
  - Mościbrodzka, Gammie, "ipole", MNRAS 2018. Open source; covariant polarized radiative transfer.
  - Vincent, Paumard, Gourgoulhon, "GYOTO", CQG 2011.
  - Cycles `kernel_path.h` for the flat-space fast path (architecture reference, no port).
- pkg40 (open) for the Kerr metric implementation that this package consumes.

---

## Prerequisites

- [ ] **Research phase (mandatory).** Use WebSearch + WebFetch to:
  1. Confirm the algorithmic approach used by RAPTOR / ipole / GYOTO for null-geodesic integration (RK4 vs RK45 vs symplectic).
  2. Confirm the redshift formula application point: per-step or per-emission?
  3. Identify which open-source repo's geodesic-integration code we can reference under a license compatible with ours.
  4. Cross-reference with Cycles' integrator structure to confirm the fast-path placement is feasible without forking the integrator.
  5. Save findings to `.astroray_plan/docs/metric-aware-tracer-research.md` with paper titles + DOIs/arXiv IDs, license of every reference repo, the specific files we will mirror, the math we will reproduce, and any open questions.
- [ ] Project owner sign-off on the research note before implementation.
- [ ] pkg40 (Kerr metric) implements the `Metric` interface that this package will exercise. If pkg40 is not yet started, this package writes the interface contract first and pkg40 implements against it.
- [ ] Confirm `gr_integrator` uses double precision; the new metric interface must accept either float (fast path) or double (curved-space path). Pillar 4 doc says "GR integrator uses double; all other rendering math uses float" — preserve that.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/metric_interface.h` | Pure-virtual `Metric` with `step(Ray& r, float dt) const` and `isFlat() const` (constexpr-friendly). Subsumes / replaces parts of the current `metric.h`. |
| `tests/test_metric_aware_path_tracer.py` | (1) Flat-Minkowski produces output identical to current `path_tracer` (bit-equality where possible, else SSIM ≥ 0.999). (2) Schwarzschild produces a deflection consistent with the analytic test in `tests/reference/schwarzschild_baseline_256.png`. (3) Spectral redshift in Schwarzschild produces measurable wavelength shift on a wide-band emission spectrum. |
| `.astroray_plan/docs/metric-aware-tracer-research.md` | Research note (created in research phase). |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/path_tracer.cpp` | At ray construction, pick the active metric (flat Minkowski by default). Hot loop branches on `metric->isFlat()`: flat path = current straight-line step; curved path = `metric->step()`. The branch is per-ray, not per-step (rays don't change metric mid-flight). |
| `include/astroray/spectrum.h` (or wherever `SampledWavelengths` lives) | Add a `redshift(float g)` method that scales wavelengths by `g`. |
| `include/astroray/gr_integrator.h` | Refactor to use `Metric::step` rather than its own loop (deduplicate). |
| `include/astroray/metric.h` | Refactor to register Schwarzschild and (future) Kerr through the new interface. |
| [.astroray_plan/docs/STATUS.md](.astroray_plan/docs/STATUS.md) | Note that Pillar 4 unblocks Pillar 5 production polish for GR. |

### Key design decisions

1. **Fast path = compile-time / inline branch on flat metric.** Approach: `inline Ray Metric::step(...) const { if (this->kind == FLAT) return r.advance(dt); ... }` — the JIT/compiler can elide the call. Verify with profiling.
2. **Per-ray metric choice.** A scene has one active metric. Per-ray choice would imply mixed-spacetime rendering, which is not physical and not in scope.
3. **Redshift at each step.** Update `SampledWavelengths` by `g_step` at every geodesic step in curved space. In flat space, `g = 1` and the multiplication is a no-op (compiler elides).
4. **Double precision for GR steps.** Convert to float at the BSDF evaluation boundary. Match existing GR convention.
5. **Spectral GR is the integration test.** A blackbody disk around a Schwarzschild metric should show measurable Doppler boosting + gravitational redshift in the rendered spectrum. This is the unification claim.

---

## Acceptance criteria

- [ ] Flat-Minkowski regression: existing path-tracer reference renders match new code at SSIM ≥ 0.999 (target: bit-identity where seed allows).
- [ ] Profiling: flat-space render time within 5% of pre-pkg67 baseline. If the slowdown exceeds 5%, the package does not close until the fast path is restored.
- [ ] Schwarzschild deflection test passes against the saved baseline.
- [ ] Spectral redshift around Schwarzschild produces a measurable shift in the output spectrum at a known emission line.
- [ ] `gr_integrator` and `path_tracer` share the same metric stepping code (no duplicate RK4 implementations).

---

## Non-goals

- Do not implement Kerr in this package (pkg40 owns it).
- Do not attempt mixed-spacetime rendering (one metric per scene).
- Do not port the wavefront GPU path here (pkg55).
- Do not change material BSDF code beyond the wavelength redshift step.

---

## Progress

- [ ] **Research phase**: literature pass + research note.
- [ ] Project owner sign-off on research note.
- [ ] Define `Metric` interface (`metric_interface.h`).
- [ ] Reimplement Minkowski + Schwarzschild against new interface.
- [ ] Refactor `path_tracer` to call through metric; verify fast-path performance.
- [ ] Wire spectral redshift.
- [ ] Tests + STATUS.md update.

---

## Realized architecture (pkg67 Option α)

The spec's literal wording — "`path_tracer` calls a `Metric` virtual to advance
rays" with a flat-Minkowski fast-path branch at the ray-advance call site —
describes an integrator design that this codebase does not use. By the time
pkg67 came up, `BlackHole` was already a `Hittable` whose `isGRObject()`
returns true; `pathTraceSpectral`'s BVH traversal dispatches into
`BlackHole::traceGRSpectral`, which runs the DP45 geodesic integrator
(`integrateGeodesic`) on a per-BH-hit basis. Flat-space objects never enter
the GR path at all; the "fast path" is the existence of `isGRObject()`
returning false, not a metric branch inside the integrator.

The owner approved **Option α**: ratify the existing dispatch and fill in the
small missing pieces, rather than refactor `pathTraceSpectral` to put the
metric branch at the ray-advance site (which would duplicate work the
dispatch already does and risk regressing the flat-space hot path the spec
explicitly protects).

What Option α delivers:

| Piece | Where | What it does |
|---|---|---|
| `MinkowskiMetric` | `include/astroray/metric.h` | Concrete flat-space `Metric` with `isFlat() == true`. Never invoked on the render path; exists to give the hierarchy a flat-space representative and to back the `"minkowski"` registry entry. |
| `"minkowski"` registry entry | `plugins/metrics/minkowski.cpp` | Symmetrises `MetricRegistry` with `"schwarzschild"` / `"kerr"`. |
| `SampledWavelengths::redshift(g)` | `include/astroray/spectrum.h`, `src/spectrum.cpp` | Applies `λ_obs = λ_emit / g` (and `pdf *= g`). Sign convention matches `NovikovThorneDisk::redshiftFactor` and the existing `dc.g` usage. |
| `GRSpectralResult::frequencyShift` | `include/raytracer.h`, `include/astroray/black_hole.h` | Exposes the per-segment accumulated `g` so the caller can redshift the continuation ray's wavelengths. Schwarzschild → 1.0 (p_t conserved); pkg40 Kerr will populate. |

What Option α does **not** do (owner decision):

- No `Metric::traceSegment` virtual.
- No metric branch in `pathTraceSpectral`'s `bvh->hit` call — the
  `isGRObject()` dispatch already routes GR hits to the per-BH integrator.
- No scene-level `Renderer::metric_` member — the per-`BlackHole` metric is
  the right granularity in this architecture.
- No removal/refactor of `BlackHole::traceGR*` or `isGRObject`.

The spec's acceptance criteria, re-stated against Option α:

- **Flat-Minkowski regression (SSIM ≥ 0.999):** holds by construction —
  Option α makes no changes to the flat-space code path.
  `tests/test_pkg67_flat_regression.py` exercises the `"minkowski"`
  registration smoke check, and runs the SSIM gate when a baseline PNG is
  present.
- **5% perf budget:** holds by construction — same reason.
  `benchmarks/pkg67_flat_perf.py` is the harness if a future measurement
  is needed.
- **Schwarzschild deflection regression:**
  `tests/test_pkg67_schwarzschild_regression.py` re-asserts SSIM ≥ 0.985
  against the committed baseline. Schwarzschild's `frequencyShift` is 1.0,
  so the render is unchanged.
- **Spectral redshift produces a measurable shift:** unit-tested in
  `tests/test_pkg67_redshift_api.py` against the documented sign
  convention. End-to-end (BH → caller → redshift continuation ray) is
  unlocked by this PR; the visible-light validation render is pkg40 Kerr
  follow-up work since Schwarzschild gives `g = 1` by symmetry.
- **Shared metric-stepping code between `gr_integrator` and `path_tracer`:**
  not applicable under Option α — `path_tracer` does not step a metric;
  it dispatches to `BlackHole`, which runs the single canonical DP45 driver.

The architect can amend the spec language later to match the realised
architecture if desired; this section is the authoritative record of what
landed.

---

## Lessons

- The spec was written before `BlackHole`-as-`Hittable` + `isGRObject()`
  dispatch landed. By implementation time, the literal Metric-step-in-hot-
  loop design was already obsolete. The Option α reroute is what made the
  package land in a session rather than a month.
- `dc.g = ν_obs / ν_emit` is the convention used by both
  `NovikovThorneDisk::redshiftFactor` and the disk-emission Planck
  evaluation. Document the sign convention on `SampledWavelengths::redshift`
  so future callers don't invert it.

