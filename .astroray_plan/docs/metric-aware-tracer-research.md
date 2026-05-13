# Metric-Aware Path Tracer Research Notes

**Target:** pkg67 implementer (future self). Read before touching `path_tracer.cpp`
or `gr_integrator.h`.
**Status:** Research complete. pkg67 is unblocked pending pkg40 Kerr interface.
**Depends on:** `.astroray_plan/docs/kerr-metric-research.md` (Kerr math foundation),
               `.astroray_plan/packages/pkg40-kerr-metric.md` (Kerr interface spec),
               `.astroray_plan/packages/pkg67-metric-aware-path-tracer.md` (impl spec)

---

## 1. The Unification Problem

### What flat-space path_tracer currently does

`path_tracer.cpp` advances a ray by:

```
ray.origin += ray.direction * t_hit;   // straight-line step
```

This assumes the spatial geometry is Euclidean and time is decoupled (Minkowski metric
g_{μν} = diag(-1, 1, 1, 1)). The affine parameter advance is trivially ds = dt for a
photon moving at c = 1.

### What curved-space integration requires

In a general stationary metric g_{μν}(x), a photon follows a null geodesic governed by:

```
d²X^μ/dλ² = -Γ^μ_{νρ} (dX^ν/dλ)(dX^ρ/dλ)
```

where λ is an affine parameter and Γ^μ_{νρ} are the Christoffel symbols of the metric.
This is a system of four coupled second-order ODEs, or equivalently an 8-ODE
first-order system on (X^μ, k^μ = dX^μ/dλ).

The null condition g_{μν} k^μ k^ν = 0 must be preserved throughout integration; it
serves as a numerical health check, not a corrector.

### Per-step work added in curved space

Compared to a straight-line step, one geodesic step (BL Kerr, RK4) costs approximately:

| Operation | Approximate FLOP count |
|-----------|------------------------|
| sin/cos of (r, θ) — done once | ~20 |
| Σ, Δ, A scalar intermediates | ~10 |
| 20 unique Christoffel symbols | ~120 |
| 12 symmetry copies | ~0 (pointer assignment) |
| 4 RK4 sub-stages × above | ~520 |
| Conservation check (E, L_z, Q) | ~30 |
| **Total per geodesic step** | **~700 FLOPs** |

A flat-space step is ~10 FLOPs (direction + t multiply-add). The overhead is real but
finite. The fast-path requirement in pkg67 eliminates this entirely for flat scenes.

---

## 2. Compile-Time Fast Path for Flat Metric

### The requirement

The journal-article claim is: *"flat-space performance preserved by a compile-time fast
path."* The pkg67 spec adds a hard constraint: flat-space render time must be within 5%
of pre-pkg67 baseline.

### The pattern: CRTP or constexpr flag

**Option A — Virtual with constexpr hint (simpler, current design):**

```cpp
class Metric {
public:
    virtual bool isFlat() const = 0;
    virtual void step(double X[4], double k[4], double dl) const = 0;
};

class MinkowskiMetric : public Metric {
public:
    bool isFlat() const override { return true; }
    void step(double X[4], double k[4], double dl) const override {
        for (int i = 0; i < 4; i++) X[i] += dl * k[i];
        // k is unchanged — no Christoffel terms
    }
};
```

In `path_tracer.cpp`, the hot loop becomes:

```cpp
if (metric_->isFlat()) {
    // straight-line advance — compiler can specialize this branch
    ray.o += ray.d * dl;
} else {
    metric_->step(X, k, dl);
}
```

If the active metric is always Minkowski (the 99% case for non-GR scenes), PGO or
branch prediction will eliminate the virtual call overhead. Verify with a profiling
build: wall time for the `isFlat()` case must be within 5% of no-branch baseline.

**Option B — CRTP (zero virtual overhead, more boilerplate):**

```cpp
template <typename Derived>
class MetricBase {
public:
    void step(double X[4], double k[4], double dl) const {
        static_cast<const Derived*>(this)->stepImpl(X, k, dl);
    }
};

class MinkowskiMetric : public MetricBase<MinkowskiMetric> {
public:
    void stepImpl(double X[4], double k[4], double dl) const {
        for (int i = 0; i < 4; i++) X[i] += dl * k[i];
    }
};
```

CRTP eliminates the virtual call entirely but requires `path_tracer` to be templated
on the metric type, which complicates the plugin registry. Use Option A unless profiling
shows the 5% budget is blown.

### What RAPTOR / ipole do

RAPTOR selects its metric at compile time via `#if (metric == BL || metric == CAR ...)`.
This is the maximally efficient approach, but it means separate binaries for each
metric — not suitable for Astroray's plugin architecture. ipole similarly uses compile-
time metric selection. Neither has a true runtime-polymorphic fast path; pkg67 must
solve this problem itself.

Reference for the flat-space path architecture: Cycles `kernel_path.h`, which branches
on scene-level BVH traversal flags. Cycles does not have a metric system, but its
branch-prediction-friendly hot-loop structure is the model for the fast path.

---

## 3. Spectral Redshift Along Geodesics

### Conservation law

Along a null geodesic in a stationary spacetime, the covariant time-component of the
photon 4-momentum is conserved (Killing symmetry):

```
E_phot = -k_t = -(g_{tt} k^t + g_{tφ} k^φ)   = const along the geodesic
```

For Kerr in Boyer-Lindquist coordinates, g_{tt} and g_{tφ} depend only on (r, θ), not
on t or φ, so both E_phot = -k_t and L_z = k_φ = g_{φφ}k^φ + g_{φt}k^t are
constants of motion.

### Redshift factor

The photon energy measured by an observer with 4-velocity u^μ is:

```
E_obs = -g_{μν} k^μ u^ν_obs
```

The redshift from emission event (e) to observation event (o) is:

```
1 + z = E_emit / E_obs = (g_{μν} k^μ u^ν_emit) / (g_{αβ} k^α u^β_obs)
```

For a zero-angular-momentum observer (ZAMO) at large r (effectively flat space),
u^μ_obs ≈ (1, 0, 0, 0) and E_obs ≈ -k_t. Since k_t is conserved, the redshift
accumulates from the emitter's own 4-velocity coupling, not from the geodesic itself.

### Per-step wavelength update

The pkg67 spec stores wavelength as a per-ray scalar. The update rule at each geodesic
step:

```
g_step = (-k_t_step) / (-k_t_start);    // ratio of conserved energies
wavelength *= g_step;                    // Δλ/λ = g_step - 1
```

In flat space, k_t is constant throughout (Minkowski has the same Killing symmetry),
so g_step = 1 and the multiply is a no-op. The compiler can elide it when metric->isFlat().

**Application point: per-emission, not per-step.** The conserved quantity k_t is
constant along the geodesic, so the total redshift can equivalently be computed once at
the emission event by comparing k^μ with the emitter's 4-velocity. However, in a
participating medium (synchrotron, ADAF, HII region), each volume element emits at a
different redshift, so the per-step update is the correct general approach. Doing it
per-step also naturally handles the Doppler boost from the emitter's orbital motion, not
just the gravitational redshift.

### Math reference

The Pandya et al. 2016 (ApJ 822, 34; arXiv 1602.08749) paper on polarized synchrotron
emissivities implicitly uses this: their transfer coefficients are computed in the
locally flat frame (tetrad frame), and the global redshift is applied by the geodesic
integrator. The covariant coupling is g_{μν} k^μ k^ν = 0 (null condition, always true
for light) — this does NOT directly give the redshift; it just confirms the ray is null.
The redshift comes from the Killing energy k_t.

Note: the task brief cited DOI 10.3847/0004-637X/823/2/100 for Pandya 2016. The ADS
record for that author/year is DOI 10.3847/0004-637X/822/1/34 (ApJ 822, 34). Verify
this DOI against ADS before submitting the journal paper section citing it.

For Pandya et al. 2018 on extended polarized radiative transfer: the Mościbrodzka &
Gammie 2018 ipole paper (MNRAS 475, 43; arXiv 1712.03057) covers the curved-space
extension. Check ADS for a 2018 Pandya et al. paper on polarized transfer; the ipole
paper is the BSD-3 reference implementation that derives from it.

---

## 4. Integrator Interaction: Fork vs. In-Place

### The question

Should pkg67 modify `path_tracer.cpp` in place (adding a metric branch to the existing
hot loop) or create a new `metric_path_tracer.cpp` that wraps or replaces it?

### In-place modification

**Pros:** The journal article can truthfully claim "the path tracer supports arbitrary
stationary spacetimes" — one integrator, two code paths. Less code duplication. The
flat-space regression test is structurally identical to the GR test.

**Cons:** Adds complexity to the most performance-critical file in the codebase. Any
regression in the flat-space code path (even from an innocent refactor touching
`path_tracer.cpp`) breaks the 5% performance budget. Merge conflicts with parallel
work on pkg64 (spectral caustics) or pkg55 (GPU wavefront) are harder to resolve when
both touch the same file.

### Forking to metric_path_tracer

**Pros:** Flat-space `path_tracer.cpp` is completely untouched — the performance
regression risk is eliminated by construction. The GR integrator can use double
precision throughout without infecting the float-precision flat-space path. Easier to
test in isolation. Easier to revert if the GR work stalls.

**Cons:** Code duplication (BSDF evaluation, Russian roulette, MIS, throughput
accumulation all copied). If the base path tracer gets bug fixes, the fork drifts.
The journal paper has to say "a new integrator was added" rather than "the integrator
was extended."

### Recommendation: in-place, with a strict interface contract

The journal-article claim is the load-bearing requirement. Use in-place modification,
but protect the flat-space path with an explicit `if (metric->isFlat())` guard at the
ray-advance call site — the only place the metric interacts with the hot loop. All
other path-tracer logic (BSDF, sampling, throughput) remains unchanged.

The implementation constraint: **the metric must not be queried inside the BSDF
evaluation or the sample-generation code.** Metric interaction is exactly one call
site: `advance_ray(ray, metric, dl)`. If you find yourself needing more than one call
site, the design is wrong.

Write the flat-space regression test (SSIM ≥ 0.999 against a pre-pkg67 reference
render) before touching any code. Gate the PR on that test passing.

---

## 5. Open Questions for the pkg67 Implementer

1. **Precision boundary.** pkg40 uses `double` for the integrator and converts to
   `float` at the BSDF boundary. Where exactly does that conversion happen?
   `GeodesicState.toFloat()` or inside `KerrMetric::step()`? Settle this in pkg40's
   interface before pkg67 starts, or pkg67 will have to redo it.

2. **Carter constant.** pkg40 monitors Carter constant Q for conservation drift. Does
   pkg67's integration loop need to expose this as a diagnostic, or is it internal to
   `KerrMetric`? If users want to log GR ray health, the integrator needs a hook.

3. **Scene-level vs. ray-level metric.** The pkg67 spec says "one active metric per
   scene." This means `path_tracer` holds a single `Metric*` for the whole render, not
   per-ray. Confirm this in the `Scene` or `Integrator` setup code. If multiple BH
   objects with different spins are ever in a scene, this assumption breaks.

4. **Wavelength array vs. scalar.** `SampledWavelengths` is a small array of hero
   wavelengths. Redshift multiplies all of them by the same g_step factor. Verify that
   the `SampledWavelengths::redshift(float g)` method (to be added in pkg67) broadcasts
   correctly and doesn't reorder the wavelength samples.

5. **GPU porting path.** The pkg55 GPU wavefront integrator is a future package. Make
   sure the `Metric` interface uses plain data arrays (double[4] for X and k) rather
   than smart pointers or STL containers, so the interface is GPU-portable without
   refactoring.

6. **GYOTO cross-validation for pkg67.** The acceptance criterion for spectral redshift
   is "measurable shift in the output spectrum at a known emission line." Define the
   test scene (Schwarzschild BH, monochromatic ring emitter at r = 8M), compute the
   expected redshift analytically (z = sqrt(g_{tt}(r_emit)) - 1 for a static emitter),
   and include both in the test file. GYOTO can independently compute the same value
   as a sanity check.

---

## Appendix: Reference Summary

| Source | Type | License | What it provides for pkg67 |
|--------|------|---------|---------------------------|
| Bronzwaer et al. 2018 (RAPTOR I) A&A 613, A2 | Paper + code | GPLv3 | Geodesic integration architecture; cross-validation only, no code |
| Bronzwaer et al. 2020 (RAPTOR II) A&A 641, A151 | Paper + code | GPLv3 | Polarized transfer in curved space; cross-validation only |
| Mościbrodzka & Gammie 2018. MNRAS 475, 43. arXiv 1712.03057 | Paper + code | BSD-3 | ipole 2nd-order symplectic integrator; may mirror |
| Pandya et al. 2016. ApJ 822, 34. DOI 10.3847/0004-637X/822/1/34 | Paper | — | Transfer coefficients in tetrad frame; math reference for redshift coupling |
| Bardeen, Press & Teukolsky 1972. ApJ 178, 347. DOI 10.1086/151796 | Paper | — | BL metric, ISCO, photon sphere; cite for test values |
| PBRT v4 spectral path tracer | Code | Apache-2.0 | Flat-space spectral hero-wavelength architecture; architectural model for fast path |

---

## Implementation-time addendum (pkg67, Option α)

Once implementation started it became clear that the unification the spec
describes — "`path_tracer` calls a `Metric` virtual to advance rays" — is
already realised in this codebase via a different (better-for-the-current-
architecture) dispatch:

- `Hittable::isGRObject()` returns true for `BlackHole` and false for
  every flat-space primitive. `path_tracer`'s BVH traversal calls
  `hit.hitObject->traceGR*` for GR objects and the normal BSDF path for
  everything else.
- `BlackHole` owns its own `SchwarzschildMetric` and runs the DP45
  geodesic integrator (`integrateGeodesic` in `gr_integrator.h`) inside
  `traceGR*`. The integrator is per-segment (one geodesic run per BH hit),
  not per-step at the ray-advance call site.
- `IntegrationResult::frequencyShift` is already computed (Schwarzschild
  → 1.0 because p_t is conserved; pkg40 Kerr will populate it).

What pkg67 (Option α) actually delivers, given that architecture:

1. **`MinkowskiMetric`** — a flat-space metric class added so the
   `Metric` hierarchy can name the flat case explicitly and so a
   `"minkowski"` entry exists in `MetricRegistry` alongside
   `"schwarzschild"` / `"kerr"`. `isFlat()` returns `true`; the
   `geodesic_rhs`/`christoffel` overrides exist only to satisfy the
   abstract base and are never invoked along the production render path
   (`isGRObject()` is the actual short-circuit).

2. **`SampledWavelengths::redshift(float g)`** — the per-ray wavelength
   shift method called out in research-note §3 ("per-step wavelength
   update"). Sign convention: `g = ν_obs / ν_emit`, so
   `λ_obs = λ_emit / g`. PDFs scale by `g` to conserve probability mass.
   Matches the convention used by `NovikovThorneDisk::redshiftFactor`
   and `BlackHole::diskEmissionSpectral`.

3. **`GRSpectralResult::frequencyShift`** — exposes the integrator's
   accumulated `g` so a caller of `Hittable::traceGRSpectral` can call
   `lambdas.redshift(g)` on the continuation ray. For Schwarzschild this
   is 1.0 (no behavioural change); for pkg40 Kerr it will carry the real
   shift.

What the spec language asks for that we deliberately did *not* do, per
Option α (owner-approved):

- No `Metric::traceSegment` virtual.
- No metric branch in `pathTraceSpectral`'s `bvh->hit` call — the existing
  `isGRObject()` dispatch already routes GR hits to the per-BH integrator.
- No `Renderer::metric_` scene-level member — the per-`BlackHole` metric
  is the right granularity here. Mixed-spacetime rendering remains out of
  scope (spec §"Non-goals").

This addendum stays in the research note so future readers understand
the gap between the spec's literal wording (per-step `Metric::step` at
the ray-advance call site) and the realised architecture (per-segment
geodesic integration inside `BlackHole`).
