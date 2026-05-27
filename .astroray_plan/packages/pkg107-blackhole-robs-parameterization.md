# pkg107 — Parameterize BlackHole `r_obs_M`

**Pillar:** 4 (Astrophysics)
**Track:** A (small C++ + Python binding change)
**Status:** open
**Estimated effort:** ½ day (~3 h)
**Depends on:** nothing

---

## Goal

**Before:** `include/astroray/black_hole.h:217` hardcodes
`r_obs_M = 100.0` inside the `BlackHole` constructor. This sets the
world-to-GR scale via `worldToGR = r_obs_M / influence_radius`. The
visible Schwarzschild-shadow angular radius (at the observer) is
`b / D = 5.196 * influence_radius / (100 * D)`, where `D` is the
camera distance to the BH centre and `5.196 = 3*sqrt(3)` is the
photon-orbit impact parameter in GR units (for M=1 geometric).

Constraint: the camera must be OUTSIDE `influence_radius` (rays
originating inside are not GR-dispatched). So `D > influence_radius`.
Combining with the shadow-size formula caps the maximum visible
shadow at ~5.2% of frame width for any allowed `(D, influence_radius)`
pair.

This makes dramatic black-hole renders (Sgr A*/M87-style large shadow
filling most of the frame) impossible without code modification.
pkg104 ran into this directly: the `gr-schwarzschild` and
`gr-kerr-94-faceon` reference scenes have small dot-shadows because
the engine wouldn't permit larger ones.

**After:** `r_obs_M` is exposed as a `BlackHole` constructor parameter
(default 100.0 for back-compat) and as a `params["r_obs_M"]` key in
`renderer.add_black_hole(...)`. Reducing it (e.g. to 20.0) shrinks the
world-to-GR scale and grows the visible shadow at the same world
camera distance.

---

## Context

The shipped behaviour is correct physics — it just embeds an
opinionated scale that suits accretion-disk visualization (where the
disk extends out to many `M`) but not BH-shadow visualization (where
you want the photon orbit boundary to dominate the frame).

PBRT-v4 and Mitsuba don't have a directly comparable parameter
because they don't ship a GR BH primitive; the closest analogue is in
RAPTOR / ipole / GYOTO where the observer screen position is
configurable in either `M` or arbitrary units.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/black_hole.h` | Constructor takes optional `r_obs_M`; defaults to 100.0. `worldToGR = r_obs_M / influence_r`. |
| `module/blender_module.cpp::PyRenderer::addBlackHole` | Read `r_obs_M` from `params` dict, forward to BlackHole ctor. |
| `tests/test_python_bindings.py` (or sibling) | Add assertion: rendering same scene with two different `r_obs_M` values produces visibly-different shadow sizes. |
| `benchmarks/reference_bank/scenes/gr-schwarzschild/scene.py` | Set `r_obs_M=20` (or owner-picked value) so the shadow grows. Re-bless reference + gate threshold. |
| `benchmarks/reference_bank/scenes/gr-kerr-94-faceon/scene.py` | Same treatment. |

### Key design decisions

**D1. Default = 100.0** to preserve existing pkg40-pkg44 visual baselines.
**D2. Parameter name `r_obs_M` matches the existing internal field name.
**D3. Bound check** — if `r_obs_M < 1.0`, log a warning (numerical
quality of GR integration starts to degrade as the observer is "close
to" the BH in M units).

---

## Acceptance criteria

- [ ] Adding `r_obs_M=20.0` to the gr-schwarzschild scene grows the
      `dark_disk` fraction from ~0.005 to ≥0.10 (about a 20× larger
      visible shadow).
- [ ] Existing pkg40-44 tests continue to pass (default 100.0).
- [ ] One regression test asserting the size scales as expected.

---

## Non-goals

- No new physics. Pure parameter exposure.
- No GR integrator changes.

---

## Progress

- [x] Spec drafted 2026-05-27 from pkg104 work (this file).
- [ ] Implement.

---

## Lessons

*(Fill in after the package is done.)*
