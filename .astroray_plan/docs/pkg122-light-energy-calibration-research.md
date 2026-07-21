# pkg122 — Dedicated-light energy calibration: Cycles derivations + evidence

**Author:** pkg122 implementer (Claude)
**Date:** 2026-07-20
**Reference oracle:** Blender Cycles, `blender/cycles` `main` branch (fetched
2026-07-20 via raw.githubusercontent.com). Apache-2.0. Files cited below are the
`src/kernel/light/*.h` and `src/scene/light.cpp` device-update path.
**Prior evidence:** `.astroray_plan/docs/pkg89-energy-audit-2026-07.md` (the GAP-2
audit that measured the per-type errors).

This note records the per-type wattage→radiance derivation against the Cycles
kernel, so the code changes are cite-and-borrow (CLAUDE.md §6), not invented.

---

## How Astroray consumes a light sample (the estimator the fixes must satisfy)

`Renderer::pathTraceSpectral` (`include/raytracer.h:2477-2496`) NEE block:

```cpp
lights.sample(ls, rec.point, rec.normal, lambdas, gen);   // ls.emission_spec, ls.pdf
...
f_spec = rec.material->evalSpectral(rec, wo, wi, lambdas); // = f_r · cosθ_x (BSDF·cosine)
L_spec = ls.emission_spec;
bsdfPdf = rec.material->pdf(rec, wo, wi);                  // SOLID-ANGLE measure
wt = (ls.pdf² ) / (ls.pdf² + bsdfPdf² + 1e-8);             // MIS power heuristic
color += throughput · f_spec · L_spec · (wt / (ls.pdf + 1e-3));
```

Two consequences that pin every fix:
1. The estimator divides `L_spec / ls.pdf`. So `emission_spec` and `ls.pdf` must
   be in **one consistent measure**.
2. `wt` combines `ls.pdf` with `bsdfPdf`, and **`bsdfPdf` is solid-angle**. So
   `ls.pdf` must **also be solid-angle**, or the MIS weight is unit-inconsistent
   and the error is size-dependent. The Cycles-calibrated geometry-emitter path
   (`light_sampler.cpp:64-70`) already returns a solid-angle pdf
   (`pdfValue(point,dir)`) with plain-radiance emission; the dedicated lights
   must match that convention.

---

## Defect 1 — AreaLight: mixed-measure pdf (0.13× at size 3, 1.40× small-far)

**Root cause.** `AreaLight::sampleLi` folded a solid-angle geometric factor
`cosθ_light/dist²` into `emission_spec` (`geometricFactor`) but returned an
**area-measure** pdf `1/area`. The `L_spec/ls.pdf` divide happens to stay
numerically correct (the `area` cancels), so the *value* was right — but `ls.pdf`
being area-measure makes the MIS weight `wt` combine an area-measure `a` with a
solid-angle `b`. `a = (1/area)·selPdf` shrinks as the light grows, so `wt`
collapses with size and the NEE contribution is under-weighted → dim, and
size-dependent (matches the audit's 7.68× vs 1.40×). This is a **measure bug in
the pdf/MIS**, exactly as the audit concluded; not a missing scalar.

**Cycles reference.** `src/kernel/light/area.h::area_light_sample` /
`area_light_eval`: emission is **plain radiance**
`ls->eval_fac = M_1_PI_F * invarea` (= (1/π)·(1/area)), and the pdf is converted
to **solid angle**:
`ls->pdf *= light_pdf_area_to_solid_angle(Ng, -ls->D, ls->t)`
(Jacobian `dist²/cosθ_light`). `src/scene/light.cpp` sets area `invarea = 1/area`.

**Fix.** Keep `emission_spec = eval·intensity·(1/area)·(1/π)` = plain radiance
`L_e = P/(πA)` (drop the `geometricFactor` fold). Return the **solid-angle** pdf
`pdf_ω = (1/area)·dist²/cosθ_light`. The `L_spec/pdf` divide reproduces the same
physical value `f_r·cosθ_x·P·cosθ_light/(π·dist²)` as before, but now `ls.pdf` is
solid-angle so MIS matches `bsdfPdf` and the geometry-emitter path → size-
independent. Verified algebraically; live-Cycles ratio pending the team-lead build.

## Defect 2 — PointLight: 1/π instead of 1/(4π) (3.59× ≈ 4× too bright)

**Root cause.** Radius-0 point radiance factor was
`normalizeFactor_(=1)·kM1PiF(=1/π)` = `1/π`. An isotropic point light of power P
has radiant intensity **I = P/(4π)** (textbook: P watts over 4π sr). The code used
`I = P/π`, i.e. **4× too large**. `evalSpectral` supplies `f_r·cosθ_x`, so the
reflected radiance is `f_r·cosθ_x·eval·(P/π)/d²` vs the analytic
`ρ·P·cosθ_x/(4π²·d²)` (with `f_r = ρ/π`). Ratio = `eval·4`; with the RGB-white
`eval` luminance ≈ 0.9 this is 3.6× — the audit's measured 3.59×. Confirmed.

**Cycles reference.** `src/scene/light.cpp` point path: `area = 4π·radius²`,
`invarea = 1/area`, `eval_fac = invarea·M_1_PI_F`. Combined with the disk pdf
`invarea_disk = 1/(π·r²)` and `light_pdf_area_to_solid_angle`, the sphere-light
estimator reduces to intensity `P/(4π)` (the `M_PI` in `area` is the 1/4π source).
`kernel/light/point.h::point_light_sample`.

**Fix.** Radius-0 point: `emission = eval·intensity·(1/(4π))·(1/d²)`, pdf = 1
(delta). Removes the factor of 4.

## Defect 3 — Blackbody: no photopic normalization (14.4× bright)

**Root cause.** `evalBlackbody` returned raw `planck(λ,T)·1e9` with **no photopic
normalization** (and a white-tint short-circuit that skipped even the geometric
normalize). Its integrated luminance `Y_planck(6500K) ≈ 3.6` (audit:
blackbody/RGB-white = 14.4/3.59 = 4.01, and RGB-white eval ≈ 0.9 → Y_planck ≈ 3.6).
So a blackbody light was ≈4× brighter than an equal-intensity RGB light, and —
compounded with Defect 2's 4× — 14.4× the analytic value. It is **not** blue: the
audit's own RGB `[21.4, 19.6, 19.7]` is near-neutral (8.4% spread, < G2's 12%);
the dominant defect is brightness.

**pkg89 Q11 / Cycles reference.** `src/scene/light.cpp::light_normalize_factor`
divides emission by its **integrated luminance** so artist intensity is stable
across temperature. `kernel/svm/svm_blackbody.h` precomputes the normalized XYZ.

**Fix.** Normalize the Planck SPD to **unit photopic luminance**:
`bbNorm(T) = 1 / ∫ planck(λ,T)·1e9·ȳ(λ) dλ`, integrated over the CIE-1964 10°
`ȳ` support (360–830 nm, 1 nm grid, the SAME `cieCmf1964_10deg` used by
`SampledSpectrum::toXYZ`). This is **self-consistent**: `E[toXYZ(evalBlackbody).Y]
= bbNorm·Y_planck = 1` for any T, independent of `planck`'s absolute scale and of
the wavelength-sampling pdf (the MC `toXYZ` estimator is unbiased for `∫Sȳdλ`).
Applied on BOTH the white-tint and tinted branches (spec §C). Chromaticity is
preserved (scalar divide), so 6500 K stays near-neutral (G2). Result: a blackbody
light has ≈ unit luminance, comparable to an RGB-white light — closing the 14×.

## SpotLight (spec requires re-derivation, not assumed)

**Two bugs.** (a) Same `1/π` intensity error as the point light (should be
`1/(4π)` — a Blender spot is a point light masked by the cone, same `eval_fac`;
`kernel/light/spot.h` inherits `spot.eval_fac` from the point path). (b) The
radius-0 spot returned pdf `1/coneSolidAngle` instead of the **delta** pdf 1, so
the `L/pdf` divide multiplied brightness by the cone solid angle (cone-angle-
dependent over-bright). `tests/test_pkg89_phase_b_dedicated_lights.py:229` already
documents the compensating "intensity cranked 100→320" hack.
**Fix.** Radius-0 spot mirrors the point light: `emission =
eval·intensity·(1/(4π))·(1/d²)·coneAtten`, pdf = 1 (delta). Radius>0 uses the
sphere-sampling pdf `1/(4π·r²)` (same as the point sphere light).

## DistantLight (spec requires re-derivation, not assumed)

**Root cause.** `emission = eval·intensity` with pdf `1/Ω` (Ω = cone solid angle).
The `L/pdf` divide multiplies by Ω, so a sun of angular size Ω≈6.6e-5 rendered at
≈6.6e-5× its intended irradiance — effectively black. Blender sun "Strength" is
irradiance S (W/m²) delivered to a normal surface; the reflected radiance is
`f_r·cosθ·S`, independent of angular size.
**Cycles reference.** `src/scene/light.cpp` sun path: `sun.eval_fac = 1/area`,
`area = π·sin²(θ_half)` = the disk solid angle; the sun's radiance is
`S·eval_fac = S/Ω`, and sampling the disk with pdf `1/Ω` yields `f_r·cosθ·S`.
**Fix.** Finite angle: `emission = eval·intensity/Ω`, pdf = `1/Ω` → net irradiance
`intensity` delivered. Zero angle (delta sun): `emission = eval·intensity`, pdf = 1.

---

## Defect 4 — RGBIlluminant vs RGBUnbounded emission convention: DEFERRED

The spec (§D) says adjudicate this **once against a live headless-Cycles A/B
render**. This implementer **cannot build the `.pyd`** (no MSVC vcvars for
subagents) and therefore cannot run the live-Cycles oracle, and the decision can
**move the 12/13-passing Cycles-parity reference bank** (owner-reserved re-bless).
Per CLAUDE.md §1 (surface forks, don't pick silently) this convention is **left
unchanged** (`evalRGB` stays `RGBIlluminantSpectrum`). After Defects 1–3, the
residual RGB-white absolute level is ≈0.9× analytic — a ~10% effect that is
exactly the Defect-4 magnitude and is left for the owner + a live-Cycles build.

**Consequence for gates.** The pkg122 regression tests gate quantities that are
**invariant to Defect 4** (area size-independence; point inverse-square; blackbody
temperature-stability and neutrality; blackbody-vs-RGB relative brightness), plus
a *loose* absolute band on the point light that catches a 4× error but tolerates
the ~10% Defect-4 residual. The tight [0.97,1.03] absolute band from the spec is
left for the team-lead's post-build live-Cycles run.

---

## GPU parity

The GPU device NEE (`src/gpu/gpu_nee.cuh::gpu_dedicated_sample`) is a hand-mirror
of the CPU `sampleLi` (not shared code), so each CPU fix is mirrored there and in
`fillDeviceParams::staticScale`. Parity (GPU==CPU) must be **re-verified on RTX by
the team-lead** — this implementer cannot build CUDA either. Changes kept 1:1 with
the CPU so parity holds by construction.

## Reference-bank re-bless list (owner-reserved — deltas pending build)

Energy of AREA (brighter), POINT (÷4), SPOT (dimmer), DISTANT (much brighter),
and BLACKBODY (÷≈3.6) all change. Scenes expected to move: pkg89 G1 (zoo), G2
(blackbody chroma — brightness only, chroma stable), G4 (spot — absolute), G5
(point hard shadow — dimmer), the pkg115 texture-grid (toward Cycles, brighter
where area-lit), and any Cycles-parity-bank scene using a dedicated light.
Measured before/after deltas require the build; implementer does NOT re-bless.
