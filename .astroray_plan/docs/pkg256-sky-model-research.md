# pkg256 — Sky-model research note (`cite-algorithm`, CLAUDE.md §6)

**Package:** pkg256 — Blender `ShaderNodeTexSky` support (bake to equirect HDRI).
**Author:** griminkel@gmail.com (Claude Code)
**Date:** 2026-09-10

---

## 1. Problem

Blender's `ShaderNodeTexSky` (`sky_type` ∈ `{SINGLE_SCATTERING,
MULTIPLE_SCATTERING, PREETHAM, HOSEK_WILKIE}`) is never converted by the
addon; a Sky-textured World falls through to the flat solid-colour fallback
(the corpus scene `world_sky_sky.blend` renders black). We need a Python-side
sky evaluator that bakes an equirectangular HDRI which loads through the
existing `renderer.load_environment_map` path (pkg63) — no engine change.

## 2. Candidate models and licences

| Model | Source | Licence | Fit for a numpy bake floor |
|---|---|---|---|
| **Preetham 1999** ("A Practical Analytic Model for Daylight", SIGGRAPH 1999) — Perez et al. all-weather luminance distribution with turbidity-linear coefficients | Preetham, Shirley, Smits 1999 (paper). Reference impl: appleseed `preethamenvironmentedf.cpp` | **MIT** (appleseed) + paper | **Chosen.** Compact closed form; all constants transcribable and verified against MIT code; no large dataset. |
| Hosek-Wilkie 2012 ("An Analytic Model for Full Spectral Sky-Dome Radiance") | `ArHosekSkyModel.{h,c}` + `ArHosekSkyModelData_*` | **BSD-3-Clause** (Lukas Hosek & Alexander Wilkie, 2012–2013) — licence header verified verbatim, see §5 | Licence-clean but requires vendoring ~40 KB of fitted coefficient tables; heavier and error-prone to reproduce for a floor bake. Considered, deferred. |
| Nishita 1993 single/multiple scattering (Blender's current default) | `intern/cycles/kernel/svm/sky.h` | **GPL** — MUST NOT copy | Excluded on licence grounds; a from-scratch single-scattering integral is disproportionate for the floor. |

### Blender's own implementations are GPL

`intern/cycles/kernel/svm/sky.h` (Nishita) and `sky_model.h` (Hosek/Preetham
port) are GPL-licensed and were **not** read for algorithm content. All maths
below comes from the 1999 Preetham paper and the **MIT-licensed** appleseed
reference implementation
(`src/appleseed/renderer/modeling/environmentedf/preethamenvironmentedf.cpp`,
Copyright 2010–2018 Francois Beaune / appleseedhq, MIT).

## 3. Model chosen: Preetham/Perez (implemented) — all four `sky_type` routed through it

The floor implements **one** licence-clean analytic model (Preetham/Perez)
and routes every `sky_type` through it (spec Key design decision 2 explicitly
permits the narrower floor). Output still varies with `sky_type`:

- `SINGLE_SCATTERING` / `MULTIPLE_SCATTERING` (Nishita family): effective
  turbidity derived from `air_density` + `aerosol_density`
  (`T_eff = 2.0 + 2.0*air_density + 8.0*aerosol_density`, clamped [1.7, 10]).
  This is an **approximation** — Blender's Nishita is a physical
  single-/multiple-scattering atmosphere with ozone/altitude; Perez is a
  fitted luminance distribution. Error is largest at low sun and in the
  circumsolar region; the sky gradient and sun azimuth/elevation are
  preserved.
- `PREETHAM` / `HOSEK_WILKIE`: use the node's `turbidity` prop directly (the
  native input for both legacy models). `HOSEK_WILKIE` is approximated with
  the Preetham distribution — Hosek is fitted to `turbidity` + `ground_albedo`
  and is more accurate near the horizon and around the sun; the ground-albedo
  and horizon-brightening differences are the dominant error.

### Perez distribution (verified verbatim vs appleseed MIT)

    F(θ, γ) = (1 + A·exp(B / cos θ)) · (1 + C·exp(D·γ) + E·cos²γ)

θ = view-direction angle from zenith, γ = angle between view direction and sun.

Turbidity-linear coefficients (T = turbidity):

    Luminance Y:  A= 0.1787T−1.4630  B=−0.3554T+0.4275  C=−0.0227T+5.3251  D= 0.1206T−2.5771  E=−0.0670T+0.3703
    Chroma x:     A=−0.0193T−0.2592  B=−0.0665T+0.0008  C=−0.0004T+0.2125  D=−0.0641T−0.8989  E=−0.0033T+0.0452
    Chroma y:     A=−0.0167T−0.2608  B=−0.0950T+0.0092  C=−0.0079T+0.2102  D=−0.0441T−1.6537  E=−0.0109T+0.0529

Zenith luminance (cd/m²), χ = (4/9 − T/120)(π − 2θs), θs = sun zenith angle:

    Yz = 1000·((4.0453T−4.9710)·tan χ − 0.2155T + 2.4192)

Zenith chromaticity (cubic in θs):

    xz: a=(0.00166T−0.02903)T+0.11693  b=(−0.00375T+0.06377)T−0.21196  c=(0.00209T−0.03202)T+0.06052  d=0.00394T+0.25886
        xz = ((a·θs+b)·θs+c)·θs+d
    yz: e=(0.00275T−0.04214)T+0.15346  f=(−0.00610T+0.08970)T−0.26756  g=(0.00317T−0.04153)T+0.06670  h=0.00516T+0.26688
        yz = ((e·θs+f)·θs+g)·θs+h

Per direction: Y = Yz·F(θ,γ)/F(0,θs); x = xz·F_x(θ,γ)/F_x(0,θs); y = yz·F_y(θ,γ)/F_y(0,θs).
Then xyY → CIE XYZ → linear sRGB (Rec.709). `cos θ` clamped to ≥ 1e-3 to keep
the horizon finite; below the horizon (θ > 90°) the sky is clamped to the
horizon value (ground band; #787 keeps it dark in-render regardless).

### Absolute scale

Preetham Yz is **photometric** (cd/m²), ~O(1e3–1e4). The engine env-map path
treats pixel values as radiance and multiplies by Background `Strength`. We
divide luminance by a fixed daylight luminous-efficacy constant
`LUM_TO_RADIANCE = 1.0/120.0` (≈ broadband daylight efficacy 120 lm/W) so a
clear zenith lands at radiance O(10) before the World `Strength` multiply.
This is a unit-bridge, not a physical spectral match — the Cycles A/B is
therefore gated loosely (±25% per sky band); measured ratios recorded in the
PR.

## 4. Sun direction (Blender Z-up world frame)

The addon exports Blender world coordinates directly to Astroray (verified:
`convert_lights` passes SUN `direction` and camera basis unswapped; Astroray
world == Blender world, Z-up). Sun direction from the node's `sun_elevation`
(E) and `sun_rotation` (A):

    sun = (cos E·cos A, cos E·sin A, sin E)   (Blender X,Y,Z; Z up)

(Lead directive overrides spec Key design decision 3's "read `sun_direction`
prop" — `sun_direction` is not reliably repopulated for the Nishita family;
elevation/rotation is the authoritative UI input and what the corpus scene
sets. Documented in the PR.)

### Equirect layout matching `EnvironmentMap` (raytracer.h)

With `blender_convention=True` and rotation 0, the loader maps world dir → env
space via `R_cswap=[[1,0,0],[0,0,1],[0,-1,0]]`, then
`θ_env=acos(dir_env.y)=acos(dir.z)` (polar from Blender +Z),
`φ=atan2(dir_env.z, dir_env.x)=atan2(−dir.y, dir.x)`, `u=0.5+φ/2π`,
`v=1−θ/π`; on load the file is flipped vertically. Net: **file row 0 = zenith
(+Z), file row H−1 = nadir; file column c ↦ φ=((c+0.5)/W−0.5)·2π**. The bake
therefore emits, for pixel (r,c):

    θ  = (r+0.5)/H · π                      (from +Z)
    φ  = ((c+0.5)/W − 0.5) · 2π
    dir = (sinθ·cosφ, −sinθ·sinφ, cosθ)     (Blender Z-up)

Sun pixel: row = (90°−E)/180°·H, col = (0.5 − A/2π)·W. This closes the loop
with the engine and is asserted in `test_pkg256_sky_bake.py` both in image
space (argmax) and through `load_environment_map`+`eval_env_rgb_upsample`.

## 5. Hosek-Wilkie BSD-3 licence text (recorded, not vendored)

Verified verbatim from `pbrt-v3/src/ext/ArHosekSkyModel.h` and
`ebruneton/clear-sky-models`:

> This source is published under the following 3-clause BSD license.
> Copyright (c) 2012 - 2013, Lukas Hosek and Alexander Wilkie. All rights
> reserved. Redistribution and use in source and binary forms, with or
> without modification, are permitted provided that … [standard 3-clause BSD].

If a future Phase-2 package wants true Hosek-Wilkie fidelity, this file may be
vendored under `external/` with the header preserved.

## 6. Sun disc

Perez/Preetham has **no** sun disc — it is a smooth luminance distribution
that peaks toward the sun. `sun_disc`, `sun_size`, `sun_intensity` are
therefore **not honoured** and are named verbatim in the runtime degradation
warning (spec Non-goal: "Sun disc rendering … explicitly named in the floor
warning as dropped"). The circumsolar Perez brightening still makes the sun
region the image argmax, satisfying the sun-position gate.

## 7. Sources

- Preetham, Shirley, Smits, "A Practical Analytic Model for Daylight",
  SIGGRAPH 1999.
- appleseed `preethamenvironmentedf.cpp` (MIT) — constant verification.
- Hosek & Wilkie, "An Analytic Model for Full Spectral Sky-Dome Radiance",
  ACM TOG 2012; `ArHosekSkyModel` (BSD-3-Clause) — licence recorded.
- Perez, Seals, Michalsky, "All-weather model for sky luminance
  distribution", Solar Energy 1993.
</content>
</invoke>
