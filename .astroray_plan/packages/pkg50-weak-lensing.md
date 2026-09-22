# pkg50 — Weak Gravitational Lensing

**Pillar:** 4
**Track:** A
**Status:** paused — Pillar 4 (Stage 2, Track L); rewritten 2026-09-22
**Estimated effort:** 2 sessions (~6 h), CPU
**Depends on:** pkg280

---

## Goal

**Before:** Astroray bends light only inside the full GR geodesic integrator
(pkg40, Kerr / Schwarzschild). There is no thin-lens model for extended mass
distributions — galaxy clusters, dark-matter halos, intervening galaxies — so the
arcs, Einstein rings and magnification patterns of deep-field images cannot be
rendered or quantitatively checked.

**After:** a CPU-only, achromatic screen-space `WeakLensing` pass in
`plugins/passes/` deflects camera rays with an analytic thin-lens field and
remaps the rendered image. The core models are a point mass
(`α = 4GM/(c²b)`) and a projected mass sheet (`α = κθ`); Phase 2 adds SIS, NFW
and a custom κ map. The pass remaps; it never rescales radiance, so specific
intensity is preserved.

**FIRST MEASURABLE DELIVERABLE.** The validation observable is
`Q = α b c² / (G M)`, with `α` the deflection in radians and `b` the
**asymptotic** impact parameter; the first-order gate is
`|Q/4 − 1| ≤ 0.01`. For Schwarzschild
`α = 4 r_g/b + (15π/4)(r_g/b)² + …`, `r_g = GM/c²` (Jia 2020,
Eur. Phys. J. C 80, 242), so the second-order term alone consumes
`≈ 2.945 r_g/b` of the relative budget and `b = 100 r_g` is **unsuitable**
for a 1 % first-order gate. The declared validity range is **`b ≥ 1000 r_g`**
(second-order ≈ 0.3 %), with finite-distance and numerical errors budgeted
separately. The observables are **independent** of the pass's own formula:
rendered background-grid image positions against the analytic lens equation;
magnification / Jacobian behaviour including the parity flip inside `θ_E`;
surface-brightness conservation on a uniform background; and, over the
overlap range, agreement with the existing geodesic tracer. A rendered
Einstein-ring radius must match
`θ_E = sqrt(4GM D_ls / (c² D_l D_s))` within **≤ 1 %** for a declared
lens/source geometry.

---

## Context

Weak lensing is a screen-space remap, far cheaper than GR geodesics, and is the
correct physical description for extended lenses at cosmological distances. The
stage plan makes Track L begin behind pkg280's audited GR transfer; this package
extends that verified path into the weak-field regime rather than standing up a
second transport. Without it, Pillar 4 Track L has only compact-object lensing
and no figure with an independent literature target. This is a CPU-only,
achromatic screen-space pass and a GPU leg is a non-goal. It depends on pkg280
(GR transfer audit) being done, and it is **not** a prerequisite for pkg279 —
the two Track L packages are independent.

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: no lensing pass exists under `plugins/passes/`; `include/astroray/pass.h` exposes only `execute(Framebuffer&)` and `name()`.
- 2026-09-22: Astra turn-2 review amendments applied (planning session).

---

## Reference

- Design: `.astroray_plan/docs/astrophysics.md §4.6`; stage plan
  `.astroray_plan/docs/stage-plan-2026-09-22.md §3 Stage 1c, §4` (Track L).
- Engine: `include/astroray/pass.h` (pkg06); `plugins/passes/`; pkg40 Kerr
  metric `plugins/metrics/kerr.cpp`; independent GR geodesic tracer
  `include/astroray/black_hole.h` (Schwarzschild path, pkg40/pkg67).
- Siblings: `.astroray_plan/packages/pkg280-gr-transfer-reference-audit.md`;
  `.astroray_plan/packages/pkg40-kerr-metric.md`.
- External: Schneider, Ehlers & Falco 1992, *Gravitational Lenses* (Springer);
  Narayan & Bartelmann 1996, *Lectures on Gravitational Lensing*
  (astro-ph/9606001); Wambsganss 1998, Living Rev. Rel. 1, 12 (lrr-1998-12);
  Bartelmann & Schneider 2001, Phys. Rep. 340, 291; Wright & Brainerd 2000,
  ApJ 534, 34 (NFW); Jia 2020, Eur. Phys. J. C 80, 242 (post-Newtonian
  Schwarzschild deflection expansion).

---

## Prerequisites

- [ ] pkg280 is done: audited GR transfer and re-baselined reference bank.
- [ ] pkg06 is done: `Pass` interface and registry exist (landed).
- [ ] Build passes on main; CPU backend only.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/passes/weak_lensing.cpp` | CPU screen-space `WeakLensing` pass: thin-lens deflection field, source-plane remap, built-in models. |
| `tests/test_weak_lensing.py` | Q deflection (`b ≥ 1000 r_g`), Einstein radius, flux conservation + parity flip, geodesic agreement, no-lens identity, pass ordering. |
| `tests/scenes/weak_lensing_deflection.py` | Deflection-vs-impact-parameter figure scene; writes the four-number evidence. |
| `tests/data/test_convergence_map.npy` | Small synthetic κ map for the Phase-2 custom-map path. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Expose the `WeakLensing` model and parameters. |
| `blender_addon/__init__.py` | Add a lensing section to the render-settings panel. |
| `CHANGELOG.md` | pkg50 entry. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg50 done at close. |

### Key design decisions

Cite the published method and add no invented physics. One model, one
screen-space pass, no new transport.

#### Phase 1 — point mass and projected mass sheet (the validation core)

- Point mass: `α = 4GM/(c²b)` radially toward the lens centre, with `b` the
  **asymptotic** impact parameter; in angular units `α(θ) = θ_E² / |θ|`.
  Projected mass sheet (uniform convergence κ): `α(θ) = κθ`, radial. Both have
  closed-form deflections — no potential solve (Schneider, Ehlers & Falco 1992
  §2; Narayan & Bartelmann 1996 §2).
- Remap: `β = θ − α(θ)`; sample the pre-lensing image at `β` with bilinear
  interpolation. `lens_model = "none"` is the identity map.
- **Declared validity range: `b ≥ 1000 r_g`**, `r_g = GM/c²`. `b = 100 r_g` is
  unsuitable: the second-order term `(15π/4)(r_g/b)²` alone is `≈ 2.945 r_g/b`
  of the first-order deflection — ~2.9 % at `b = 100 r_g`, against a 1 % gate.
  At `b = 1000 r_g` the same term is ≈ 0.3 %; the remaining ≤ 1 % budget is for
  finite-distance and numerical error, budgeted separately.
- **Non-circularity:** testing the pass's inserted `4GM/(b c²)` formula against
  itself proves nothing. The validation observables must be independent of the
  implementation: (a) rendered image positions of a background grid against the
  analytic lens equation; (b) magnification / Jacobian behaviour, including the
  parity flip inside `θ_E`; (c) surface-brightness conservation on a uniform
  background; (d) for `b` in the overlap range, agreement with the existing
  geodesic tracer `include/astroray/black_hole.h` (Schwarzschild path,
  pkg40/pkg67) — the independent GR propagation.
- CPU-only and achromatic: the deflection is independent of λ. GPU is a
  non-goal.

#### Phase 2 — extended lenses

- SIS (`α = θ_E`, constant magnitude), NFW (Wright & Brainerd 2000), and a
  custom κ map. The custom map solves `∇²ψ = 2κ` by FFT
  (`ψ̂ = 2κ̂ / (k₁² + k₂²)`) and sets `α = ∇ψ`. These are image-geometry
  diagnostics and are not required for the Phase-1 deliverables.

#### Surface-brightness conservation

- Lensing preserves specific intensity: the pass remaps, never rescales,
  radiance. Flux changes only through the source-to-image area Jacobian
  `μ = 1 / det A`. The uniform-background check confirms the remap creates no
  spurious flux (≤ 1 %).
- A point source is magnified by `μ` and forms a ring at `θ_E`; that is a
  geometry check, not an energy violation.
- Inside `θ_E` the Jacobian determinant changes sign, so the image is
  parity-flipped; the test asserts the observed parity flip at the predicted
  radius, not merely a magnification value.

#### Pass ordering and registration

- After rendering, before denoising: the denoiser guide buffers are pre-lensing
  and would be inconsistent post-remap.
- Register with `ASTRORAY_REGISTER_PASS("weak_lensing", WeakLensing)`.

---

## Acceptance criteria

- [ ] `Q = α b c²/(G M)` reaches 4 within ≤ 1 % (`|Q/4 − 1| ≤ 0.01`) over
      `b ≥ 1000 r_g`, using the asymptotic `b`.
- [ ] Rendered Einstein-ring radius matches
      `θ_E = sqrt(4GM D_ls / (c² D_l D_s))` within ≤ 1 % for a declared
      lens/source geometry.
- [ ] Uniform-background flux conservation within ≤ 1 % over a fixed aperture,
      with the parity flip inside `θ_E` observed at the predicted radius.
- [ ] Deflection agrees with the independent geodesic tracer
      `include/astroray/black_hole.h` (Schwarzschild path, pkg40/pkg67) within
      ≤ 1 % over the overlap range.
- [ ] `WeakLensing` registered via
      `ASTRORAY_REGISTER_PASS("weak_lensing", WeakLensing)`.
- [ ] `lens_model = "none"` produces a pixel-identical image to no pass.
- [ ] Pass runs after rendering and before denoising when both are active.
- [ ] Blender addon exposes model selection and parameters.
- [ ] ≥ 6 tests cover the four numbers plus no-lens identity, pass ordering and
      model selection.
- [ ] All existing tests pass.

---

## Non-goals

- Do not implement a GPU leg: the pass is CPU-only and achromatic.
- Do not implement chromatic or wavelength-dependent deflection.
- Do not implement multiple-image / strong lensing (κ > 1) — the GR integrator
  (pkg40) is the correct tool.
- Do not implement time delays, flexion, or shear catalogues.
- Do not implement cluster lensing or grating (#141) — deferred candidates.
- Do not integrate rays through a 3D mass distribution; screen-space thin lens
  only.

---

## Progress

- [ ] Phase 1: point-mass and mass-sheet deflection + source remap.
- [ ] Phase 1: deflection figure, Einstein-radius and flux-conservation tests.
- [ ] Phase 2: SIS / NFW + FFT custom κ map.
- [ ] Wire as post-process pass; Blender UI.
- [ ] Full suite green; update `CHANGELOG.md`, `.astroray_plan/docs/STATUS.md`.

---

## Lessons

*(Fill in after the package is done.)*
