# pkg50 — Weak Gravitational Lensing

**Pillar:** 4
**Track:** A (uses GR machinery)
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg40 (Kerr metric), pkg06 (pass registry)

---

## Goal

**Before:** Gravitational lensing in Astroray only occurs via the full
GR geodesic integrator around compact objects. There is no way to
render the lensing effects of extended mass distributions — galaxy
clusters, dark matter halos, or intervening galaxies — which produce
the characteristic arcs, Einstein rings, and magnification patterns
seen in HST and JWST deep fields.

**After:** A `WeakLensing` post-process pass deflects background rays
according to a user-supplied convergence (κ) and shear (γ) map. A
`PointMassLens` mode provides analytic lensing from a single point
mass (Einstein ring). The pass integrates with the existing pass
registry so it runs after rendering and before denoising.

---

## Context

Weak lensing is computationally cheap (screen-space image remapping)
compared to full GR ray tracing, and is the correct physical
description for lensing by extended mass distributions at cosmological
distances. It is visually striking — gravitational arcs around galaxy
clusters are among the most iconic images in astronomy.

Strong lensing (multiple images, caustics) from compact objects is
already handled by the GR integrator. This package covers the
complementary regime: extended lenses where the thin-lens
approximation is valid.

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.6`
- Bartelmann & Schneider 2001 — "Weak Gravitational Lensing" (review)
- Narayan & Bartelmann 1996 — lensing formalism (lectures)
- Pass registry: `include/astroray/pass.h` (from pkg06)

---

## Prerequisites

- [ ] pkg06 is done: pass registry and `Pass` interface exist.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/passes/weak_lensing.cpp` | `WeakLensing` post-process pass. |
| `tests/test_weak_lensing.py` | Unit and integration tests. |
| `tests/data/test_convergence_map.npy` | Small synthetic κ map for testing. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Expose lensing pass parameters. |
| `blender_addon/__init__.py` | Add lensing section to render settings panel. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg50 done. |
| `CHANGELOG.md` | Add pkg50 entry. |

### Physics model

#### Thin-lens formalism

For each pixel at angular position **θ** on the image plane, the
true source position is:

    **β** = **θ** − **α**(**θ**)

where **α** is the deflection angle. In the weak-lensing regime, the
deflection is related to the convergence κ and shear γ by:

    α₁ = ∂ψ/∂θ₁,  α₂ = ∂ψ/∂θ₂

where ψ is the lensing potential satisfying ∇²ψ = 2κ.

#### Implementation as image remapping

The pass operates on the rendered image as a post-process:

1. **Input**: user-supplied convergence map κ(θ₁, θ₂) as a 2D
   floating-point image (`.npy` or `.fits`), or analytic parameters
   for built-in lens models.
2. **Compute deflection field**: solve ∇²ψ = 2κ via FFT
   (ψ̂ = 2κ̂ / (k₁² + k₂²)), then compute α = ∇ψ via inverse FFT.
3. **Remap**: for each output pixel at θ, sample the pre-lensing
   image at β = θ − α(θ) using bilinear interpolation.

The FFT approach is O(N log N) for an N-pixel image and handles
arbitrary convergence maps.

#### Built-in lens models

| Model | Parameters | Deflection |
|---|---|---|
| Point mass | Einstein radius θ_E, centre | α = θ_E² / |θ − θ_c| (radial, toward centre) |
| SIS (singular isothermal sphere) | θ_E, centre | α = θ_E (constant magnitude, radial) |
| NFW (Navarro-Frenk-White) | M_200, c, z_lens, z_source | Analytic κ(r) from Wright & Brainerd 2000 |

For built-in models, the convergence map is computed analytically on
the pixel grid — no FFT needed for the deflection (it has closed-form
expressions).

#### Parameters

| Parameter | Default | Description |
|---|---|---|
| `lens_model` | "none" | "none", "point_mass", "sis", "nfw", or "custom". |
| `convergence_map` | None | Path to custom κ map (for `lens_model = "custom"`). |
| `einstein_radius` | 1.0 arcsec | For point mass / SIS models (in pixel units). |
| `lens_centre` | image centre | Position of lens centre (pixel coordinates). |
| `nfw_mass` | 1e15 M_sun | For NFW model. |
| `nfw_concentration` | 5.0 | For NFW model. |

### Key design decisions

1. **Post-process pass, not ray modification.** Weak lensing as a
   screen-space remap is both physically appropriate (the thin-lens
   approximation) and architecturally clean. It runs after the
   renderer produces the unlensed image, avoiding any coupling to the
   ray-tracing loop.

2. **FFT for custom maps, analytic for built-ins.** FFT-based
   potential solving handles arbitrary mass distributions. Built-in
   models skip the FFT since their deflections are known analytically.
   Both paths produce the same data structure (a 2D deflection field).

3. **Pass ordering: lensing before denoising.** The lensing remap
   should run before OIDN because the denoiser's guide buffers (normal,
   albedo) are pre-lensing and would be inconsistent post-remap. In
   practice the difference is small, but the correct ordering is
   lensing → denoise.

4. **No multiple-image handling.** The remapping samples the source
   plane at a single position per output pixel. In the strong-lensing
   regime (κ > 1), this misses multiply-imaged sources. This is a
   known limitation of the screen-space approach; for strong lensing
   around compact objects, the GR integrator (pkg40) is the correct
   tool.

---

## Acceptance criteria

- [ ] `WeakLensing` registered via
      `ASTRORAY_REGISTER_PASS("weak_lensing", WeakLensing)`.
- [ ] Point mass model: a background star field rendered through a
      point-mass lens shows a visible Einstein ring at the specified
      radius.
- [ ] SIS model: tangential arcs visible around the lens centre.
- [ ] Custom convergence map: a synthetic Gaussian κ map produces
      smooth, radially symmetric magnification.
- [ ] Deflection field is divergence-consistent: ∇·α ≈ 2κ (verified
      numerically on the computed deflection grid to < 5%).
- [ ] Pass runs after rendering and before denoising when both are
      active.
- [ ] No-lens mode (`lens_model = "none"`) produces a pixel-identical
      image to no pass at all.
- [ ] Blender addon exposes lensing model selection and parameters.
- [ ] All existing tests pass.
- [ ] ≥6 new tests covering: point mass ring, SIS arcs, custom map,
      deflection consistency, no-lens identity, pass ordering.

---

## Non-goals

- Do not implement strong lensing with multiple images. Use the GR
  integrator for compact-object lensing.
- Do not implement time-delay calculations between multiple images.
- Do not implement shear measurement / shape catalogues (observation
  pipeline, not rendering).
- Do not implement flexion (higher-order lensing).
- Do not implement cosmological distance calculations. User specifies
  Einstein radius directly in pixel units.

---

## Progress

- [ ] Implement deflection computation for point mass and SIS.
- [ ] Implement NFW convergence profile + FFT potential solve.
- [ ] Implement custom convergence map loading.
- [ ] Implement image remapping with bilinear interpolation.
- [ ] Wire as post-process pass.
- [ ] Add Blender UI.
- [ ] Write tests.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*
