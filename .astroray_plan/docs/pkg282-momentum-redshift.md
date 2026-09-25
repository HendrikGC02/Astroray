# pkg282 — momentum-based thin-disk redshift, r_obs offset, dark-ring artifact (2026-09-25)

## Redshift g (implemented)

`g = ν_obs/ν_em = (k·u)_obs/(k·u)_em`. Observer static at infinity (u = ∂_t; the
influence-sphere exterior is flat, so the camera is in the asymptotic region).
Emitter on a prograde circular equatorial Kerr orbit, u = u^t(∂_t + Ω∂_φ):

    g = 1 / (u^t (1 − Ωλ)),   λ = −k_φ/k_t
    Ω = √M/(r^{3/2} + a√M),   u^t = (r^{3/2} + a√M) / (r^{3/4} √(r^{3/2} − 3M r^{1/2} + 2a√M))

- Cunningham 1975, ApJ 202, 788 (DOI 10.1086/154033): g = 1/(u^t(1−Ωλ)).
- Bardeen, Press & Teukolsky 1972, ApJ 178, 347, eqs. 2.12/2.16: Ω and u^t.
- Pattern: ipole `radiation.c::get_fluid_nu` (BSD-3, momentum-based fluid-frame
  frequency). No code copied. GYOTO (GPL-3.0) used only as an external executable.

k_t and k_φ are Killing-conserved, so λ is taken once from the initial state. λ does
not change under k → −k, so the past-directed traced momentum works directly.
At a=0 and λ=0 this reduces to the old √(1−3M/r). Inclination no longer enters. The
viewing geometry is the camera's. `BlackHole(incl_deg)` is ignored.

Interim: the emitter kinematics use the geodesic spin, but flux, T(r) and r_in stay
on the a=0 Page–Thorne model (r_in = 6M). Kerr Page–Thorne is #894 and was not needed
for this gate. GYOTO's fixture also used r_in = 6M.

**Gate** (frozen pkg280 Phase 3 procedure, first-crossing g from
`astroray_test_helpers.gr_disk_redshift_image`, 512², i=90):

| | Astroray δ | GYOTO δ | mismatch |
|---|---|---|---|
| a=0 | +0.2131 (g_L 0.700, g_R 1.079) | +0.2156 | 1.2 % |
| a=0.94 | +0.2021 (g_L 0.691, g_R 1.041) | +0.2029 | 0.4 % |

The absolute side medians are about 2 % below GYOTO's. The ratio δ is what the gate
checks. Render level: disk-only band R/L flux was 0.998 before and is 2.38 now (a=0.94).

## pkg107 "0.37×" shadow offset (derived)

The exterior of the influence sphere is flat, so a camera at world distance D sits at
D_eff = D·r_obs/R M, not at r_obs. A ray at angle θ has
b = D_eff sinθ / √(1 − (2M/r_obs) sin²α), with sin α = D sinθ/R. This follows from
`buildInitialState`'s null condition. The ray is captured if b < 3√3 M, so the small-angle
θ_s ≈ (R/D)·3√3M/r_obs. pkg107's reference 3√3M/r_obs assumed the observer at r_obs,
which gives a ratio of R/D = 5/12 = 0.417. pkg107's linear pixel→angle conversion (0.948)
and its soft luma-threshold/area estimate brought that down to the measured 0.355–0.386.
Probe capture radius vs the closed form: r_obs 20/40/80 → 67.07/33.44/16.74 px vs
67.07/33.49/16.73 px (≤0.3 %). Not a defect. Locked by `test_pkg282_momentum_redshift.py`.

## 74–78 px partial dark ring (cause found, not fixed)

The path tracer respawns a GR continuation from the **entry** point
(`Ray next(rec.point, exitDir)` in `raytracer.h`) rather than from the geodesic's exit
point. For rays at about 74–78 px (a=0), the exit direction is near-tangent to the sphere
at the entry point. The continuation clips the sphere again and ping-pongs: the probe
counts 3–8+ passes in 264 of the 1916 pixels in that annulus, and ≥5 passes in 220 of
them (11 %). The rendered mask was 8–10 % dark there. Once max depth (5) is exhausted, the pixel
goes black. This is a real artifact, not a benign one. Fix: spawn the continuation from
the exit position, which touches `GRResult` and 3 dispatch sites. That is outside
pkg282's owned files, so it needs a follow-up.
