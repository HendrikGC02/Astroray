# pkg282 — Momentum-based redshift and the pkg107 shadow-size offset

**Pillar:** 4
**Track:** A
**Status:** done
**Estimated effort:** 2 sessions (~6 h), CPU
**Depends on:** pkg280

---

## Goal

Before: `NovikovThorneDisk::redshiftFactor` computes `g` from
`sin(i_param)·sin(φ_emit)` — a flat-space approximation that ignores the
photon's actual momentum and uses the *declared* inclination parameter
instead of the camera's real viewing geometry, producing δ≈0 asymmetry where
GYOTO measures +0.20. Separately, `r_obs_M` scales the shadow radius
correctly but its absolute size is a fixed ~0.37x of the idealized textbook
formula, unexplained. After: `g` is derived from the photon's conserved
momentum, inclination comes from camera geometry (not a declared parameter),
the disk redshift asymmetry matches GYOTO within gate, and the 0.37x offset
is either derived analytically or documented as an intentional, understood
consequence of the finite-camera/entry-sphere mapping.

---

## Context

pkg280 Phase 3 found this is the second of two independent root causes
behind the Kerr cross-check failure (the first, spin, is pkg281). Even after
pkg281 fixes the metric, the redshift asymmetry will still be wrong because
the formula never reads `p_φ`/`p_t`. pkg280 Phase 4 also surfaced the
unexplained 0.37x shadow-size offset (pkg107); it belongs here because both
concern how the camera/geodesic solution maps to on-screen quantities.

---

## Evidence

- 2026-09-24: `NovikovThorneDisk::redshiftFactor` (`include/astroray/accretion_disk.h`) uses `sqrt(1-3/r)/(1+Omega*r*sin(i_param)*sin(phi_emit))`, ignoring photon momentum; at i=90° (the scene's actual rendered geometry) this is azimuthally uniform regardless of the declared inclination parameter.
- 2026-09-24: Phase 3 (`astra_run/batchB-phase3/RESULT.md`): Astroray disk-only L/R flux ratio 0.998 (δ≈0) vs GYOTO a=0.94, i=90 δ=+0.203 (g_L 0.705, g_R 1.064) — ~100 % mismatch. At declared i=78°, GYOTO gives δ=+0.299 (a=0.94) / +0.306 (a=0) — mismatch also ~100 % there.
- 2026-09-24: pkg107 (`astra_run/batchB-phase24/RESULT.md`): θ scales inverse-linearly with `r_obs_M` as expected (ratios 0.483x/0.475x vs ideal 0.5x), but the absolute ratio to `3√3·M/r_obs` is ≈0.355–0.386 across `r_obs_M` ∈ {20,40,80}, not 1.0. Cause unproven.

---

## Reference

- `.astroray_plan/docs/gr-transfer-audit-2026-09.md` §Phase 3, §Phase 2/Phase4/pkg107, §Four numbers.
- `.astroray_plan/packages/pkg280-gr-transfer-reference-audit.md`; `.astroray_plan/packages/pkg107-blackhole-robs-parameterization.md`.
- Frozen comparison metadata: `C:/Users/hgcom/OneDrive/Astroray/astra_run/batchB-phase3/NOTES.md`.
- External: Rybicki & Lightman 1979 §4.2; Cunningham 1975, ApJ 202, 788; Moscibrodzka & Gammie 2018, MNRAS 475, 43 (ipole, BSD-3 — `radiation.c::get_fluid_nu`, momentum-based fluid-frame frequency, no code copied); Vincent et al. 2011, CQG 28, 225011 (GYOTO, GPL-3.0 — external executable oracle only).

---

## Prerequisites

- [ ] pkg280 is done.
- [ ] pkg281 lands first (or in parallel) so the metric under test is actually Kerr a=0.94, not Schwarzschild.
- [ ] Build passes on main. CPU backend only.

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/accretion_disk.h` | Replace `redshiftFactor`'s flat-space `sin(i)·sin(φ)` formula with `g = (k·u)_obs / (k·u)_em`, using the photon's conserved momentum (`p_φ`, `p_t`) from the geodesic integration and the disk fluid's 4-velocity `u`. Inclination is read from the camera's actual geometric orientation, not a separate declared scene parameter. |
| `include/astroray/black_hole.h` | Wire the photon momentum at the disk-hit point through to `redshiftFactor` if not already available there. |
| `plugins/metrics/kerr.cpp` | Ensure conserved quantities (`p_φ`, `p_t`, or equivalent) are exposed per hit for pkg281's Kerr integrator. |
| `benchmarks/reference_bank/scenes/gr-kerr-94-faceon/gates.toml` | Add a redshift-asymmetry gate once the new render is measured. |

### Key design decisions

Cite the published invariant (Rybicki & Lightman; ipole's momentum-based
`get_fluid_nu` as the pattern, no code copied — same posture as pkg280's
`diskEmissionSpectral` fix). For the pkg107 offset: first attempt an
analytic derivation from the finite-camera/entry-sphere geometry (the
influence-sphere-to-camera straight-line mapping documented in pkg280 Phase
4); if no closed form is found within this package's budget, document the
measured constant and its stability across `r_obs_M` as the accepted
normalization, per pkg280's non-goal boundary (no new physics).

---

## Acceptance criteria

- [x] `redshiftFactor` (or its Kerr-aware replacement) derives `g` from photon momentum, not a declared inclination parameter.
- [x] Re-run the pkg280 Phase 3 disk-redshift procedure against GYOTO: asymmetry δ within **≤ 5 %** at both a=0 and a=0.94 (i=90 geometric match). Measured 1.2 % (a=0) and 0.4 % (a=0.94).
- [x] pkg107 0.37x offset: either an analytic derivation is added and cited, or the measured constant is documented as fixed/stable with the derivation left as a named unresolved item — no case is closed silently. Derived: the camera sits at D·r_obs/R M, so the ratio is R/D = 0.417. The closed form matches the probe to ≤0.3 %.
- [x] The faint 74–78 px partial ring in the Astroray capture mask (Phase 3 side observation) is investigated and its cause recorded (fixed or explained as benign). Cause: the GR continuation respawns from the entry point and ping-pongs until max depth runs out. This is a real artifact. The fix is outside the owned files and needs a follow-up.

---

## Non-goals

- Do not touch spin/metric selection (pkg281's scope).
- Do not implement ADAF/synchrotron transport (pkg283).
- Do not add GPU GR code.

---

## Progress

- [x] Derive `g` from photon momentum in `redshiftFactor`. `g = 1/(u^t(1−Ωλ))`, with Kerr Ω and u^t from the geodesic spin. Flux stays a=0 (#894).
- [x] Re-run GYOTO redshift-asymmetry comparison; confirm ≤5 %. Uses `astroray_test_helpers.gr_disk_redshift_image`. Test: `tests/test_pkg282_momentum_redshift.py`.
- [x] Investigate pkg107 0.37x offset.
- [x] Investigate the 74-78 px partial ring artifact.
- `gates.toml` gate not added. The bank frame saturates the disk on both sides (linear 3–6, so clamped to 1), and no image gate could see the asymmetry. The gate lives in the probe test instead. The Kerr SSIM (0.543) is pkg281's un-reblessed reference: the pkg281 render scores 0.545, and pkg282 vs pkg281 is 0.993.
- Evidence: `astra_run/gr/pkg282/`. Note: `.astroray_plan/docs/pkg282-momentum-redshift.md`.

---

## Lessons

- A per-pixel g probe beats inferring g from rendered flux. With it, δ vs GYOTO became a direct, cheap unit test.
- Compare δ, not absolute g. The absolute side medians sit about 2 % below GYOTO's, but δ agrees to about 1 %.
