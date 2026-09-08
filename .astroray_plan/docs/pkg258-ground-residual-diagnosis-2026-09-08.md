# pkg258 ground-row residual diagnosis — 2026-09-08

Follow-up to `hdri-background-gap-diagnosis-2026-09-07.md`'s open residual
(2026-09-08 addendum): after pkg258 landed environment NEE, Astroray's ground
strip on `hdri_exterior_hair` is 7-17% darker than Cycles (blue worst),
though the sky strip matches exactly. This session isolates the cause.

**Setup (all experiments unless noted):** headless Blender 5.2,
`benchmarks/blender_parity/scenes/hdri_exterior_hair.blend`, 160x90, Standard
view transform / exposure 0 / gamma 1 / EXR float (matching
`render_leg.py::_configure_render`), 32 spp, `scene.cycles.seed=7`, adaptive
sampling and both scene- and view-layer denoising off. Astroray =
`dist/astroray/astroray.cp313-win_amd64.pyd`, OpenMP-off CPU build of
post-#751 main (built 08:47 2026-09-08; canary
`hasattr(Renderer(),'set_env_nee')` True; no engine-code commits landed
between that build and this session's `origin/main` HEAD `32c39836`, verified
via `git log --since="2026-09-08 08:47" -- include/ src/ module/ plugins/`).
Driver: `test_results/2026-09-08-pkg258res/run_ground_residual.py` (worktree-
local, not committed; applies the `render_leg.py::_to_top_down` bottom-up fix
BEFORE measuring any ROI — the 2026-09-07 driver's raw arrays are NOT
top-down-corrected and were not reused here). Ground ROI = bottom 30/360 of
the frame (the "near ground band" the residual was originally measured on,
matching the pre-#749-flip `HDRI_BACKGROUND_ROI`); sky ROI = top 30/360
(current `harness.py::HDRI_BACKGROUND_ROI`). Evidence PNGs (sRGB, ROI boxes
drawn: green=sky, magenta=ground) copied to
`.astroray_plan/docs/pkg258-ground-residual/`.

## Experiment table

| # | Variant | Astroray ground mean | Cycles ground mean | ratio | R | G | B | Verdict |
|---|---|---|---|---|---|---|---|---|
| E0 | Full scene, stock materials, env NEE | 0.11192 | 0.12111 | 0.924 | 0.942 | 0.911 | 0.918 | Reproduces the addendum (0.925, 0.946/0.921/0.914) within 32-spp MC noise. `e0_full_scene.png` |
| E1 | Full scene, `sample_clamp_direct=0`/`sample_clamp_indirect=0` (explicit) vs Blender's own scene defaults (`direct=0.0`, `indirect=10.0` — verified via a fresh factory-startup scene) | 0.11200 | 0.12111 | 0.925 | 0.943 | 0.912 | 0.918 | **No change** (Δ 0.00008, <0.1%). Clamp cleared: code read confirms why — `clampContribSpectral` (`include/raytracer.h:2460`) only applies `clampIndirect` at `bounce>0`; every camera-visible Ground pixel's env-NEE contribution fires at `bounce==0`, which uses `clampDirect` (0, already disabled by Blender's own scene default). |
| E2a | Full scene, Hair hidden (`hide_render`+`visible_camera=False`, both engines) | 0.11061 | 0.12016 | 0.921 | 0.936 | 0.908 | 0.918 | Unchanged from E0 (0.924→0.921). Hair occlusion is not the cause. |
| E2b | Ground only (Hair+Scalp+GlassSphere all hidden, both engines) | 0.10776 | 0.11634 | 0.926 | 0.946 | 0.919 | 0.913 | **Unchanged from E0/E2a.** Occlusion/shadowing from any of the three other objects is ruled out — the identical deficit exists with the Ground plane and HDRI alone. `e2_ground_only.png` |
| E3a | Ground-only, Ground material → plain Diffuse BSDF, same colour (0.25,0.27,0.24), roughness 0 | 0.11935 | 0.10773 | **1.108** | 1.088 | 1.072 | 1.175 | **Sign flips.** A pure Lambertian at the identical colour makes Astroray 11% *brighter* than Cycles, not darker. `e3_plain_diffuse.png` |
| E3b | Ground-only, Diffuse BSDF, neutral grey (0.5,0.5,0.5) | 0.20626 | 0.21233 | 0.971 | 0.957 | 0.964 | 0.995 | Small (-2.9%) deficit, blue now the *best*-matching channel. |
| E3c | Ground-only, Diffuse BSDF, dark grey (0.25,0.25,0.25 — same magnitude as the ground colour, no hue) | 0.11813 | 0.10617 | 1.113 | 1.077 | 1.099 | 1.168 | Matches E3a almost exactly (1.113 vs 1.108) — the overshoot tracks **magnitude** (~0.25 vs ~0.5), not hue. |
| E3d | Ground-only, stock Principled, roughness **0** (Base Color unchanged) | 0.11862 | 0.11998 | **0.989** | 1.006 | 0.984 | 0.975 | Matches Cycles within 32-spp MC noise. |
| E3e | Ground-only, stock Principled, roughness **0.85** (= stock scene) | 0.10776 | 0.11634 | 0.926 | 0.946 | 0.919 | 0.913 | Identical to E2b (sanity check). **The deficit is present at roughness 0.85 and absent at roughness 0, everything else equal.** `e3_roughness_sweep.png` |
| E4a | Sun lamp only (HDRI removed, explicit zero Background node — no env NEE, no envMap loaded at all), stock Principled, roughness 0 | 0.16180 | 0.16178 | **1.0001** | 1.017 | 0.999 | 0.984 | Matches Cycles exactly under ordinary **lamp NEE**, no env NEE in the picture. |
| E4b | Sun lamp only, stock Principled, roughness 0.85 | 0.18192 | 0.19430 | **0.936** | 0.952 | 0.936 | 0.921 | **Same ~6-7% deficit reappears with NO env NEE and NO HDRI at all.** `e4_lamp_no_env_nee.png` |
| E5 | Sun lamp only, Principled roughness 0.85, Base Color forced to neutral grey (0.26,0.26,0.26) | 0.18640 | 0.19912 | 0.936 | 0.940 | 0.942 | 0.927 | Same ~6.4% deficit, now nearly channel-uniform (spread 1.5pp vs E4b's 3.1pp). `e5_achromatic_control.png` |

Row-band ratio (E0, 9 equal bands, bottom→top, whole-RGB mean, Astroray/Cycles):
0.921 / 0.895 / 0.840 / 0.853 / 0.896 / 0.957 / 0.979 / 1.002 / 1.001 — matches
the addendum's 0.93/0.90/0.83/0.84/0.90/0.96/0.99/1.00/1.00 pattern (worst in
the mid-ground bands, sky bands at 1.00).

## Root cause

**Not env NEE, not the firefly clamp, not hair/scalp/glass occlusion.** The
deficit is entirely reproduced by Ground + any light source at Principled
roughness 0.85, and entirely absent at roughness 0 — including under a plain
Sun lamp with env NEE completely out of the picture (E4). This decisively
rules out every candidate pkg258 itself could own:

- **(a) firefly clamp** — cleared by E1 (no measurable change) and explained
  by the code read: `bounce==0` env-NEE/lamp-NEE contributions at the
  camera-visible Ground use `clampDirect`, which is 0 (disabled) by Blender's
  own default, never `clampIndirect` (10.0 default).
- **(c) hair/scalp/glass occlusion** — cleared by E2a/E2b: removing every
  other object leaves the deficit unchanged (0.924→0.926).
- **(b) env NEE sun-disc pdf/estimator bias** — cleared by E4: the same
  magnitude of deficit (0.936) appears under a Sun lamp using ordinary lamp
  NEE, with the HDRI removed and no `EnvironmentMap` loaded at all, so no env
  NEE code path can be involved.
- **(d) spectral-upsampling of the ground's albedo, as the dominant term** —
  E3d/E3e/E4a/E4b show the deficit is gated by **roughness alone** (0 → none,
  0.85 → ~6-7%) at the *same* albedo, which a pure upsampling-of-colour
  hypothesis does not predict. E5 (grey albedo, same roughness) still shows
  the same ~6.4% deficit, confirming roughness — not colour — drives the
  bulk of it.

**Root cause: Astroray's Principled BSDF loses ~6-7% too much diffuse energy
at high specular roughness (0.85), independent of light source, NEE
strategy, or material colour.** The likely mechanism, from a code read of
`plugins/materials/principled.cpp` (not verified by a numeric LUT
comparison — see "Outstanding" below): the diffuse lobe's incoming weight is
attenuated by the specular layer's directional-hemispherical albedo via
`layeringWeightAfter` (`principled.cpp:663`), fed by
`ggxDirectionalAlbedo`/`DisneyEnergyCompensationTables::ggxE`/`ggxEavg`
(`:638-648`, `include/astroray/energy_compensation.h`) at the material's
`roughness_`. `layeringWeightAfter`'s own comment admits it is an
approximation of Cycles' `bsdf_util.h closure_layering_weight` ("equivalent
for weight≈1" — Cycles computes a single `saturate(1 - max_channel(albedo /
weight))` scalar attenuation, Astroray applies `1 - albedo` **per channel**);
for this achromatic-Fresnel dielectric case with `weight≈(1,1,1)` the two
formulas should coincide, so the approximation gap does not fully explain the
finding by itself — but the roughness-gated, LUT-driven `ggxDirectionalAlbedo`
value at roughness 0.85 is the only remaining roughness-dependent quantity in
this lobe's weight chain and is the most likely site of the actual numeric
error. This is corroborated by an existing, already-landed tolerance:
`tests/test_principled_bsdf.py::test_principled_diffuse_lambert_energy_conservation`
and its GPU twin (`tests/test_pkg178_principled_gpu_furnace.py`) already
assert only a **floor of 0.85** (i.e. up to 15% energy loss tolerated) for
Principled diffuse at roughness **0.5** against a white-Lambertian reference
— a self-referential (Astroray vs Astroray) tolerance, not a Cycles-parity
one, that was evidently calibrated without checking whether Cycles itself
loses that much energy at the same roughness. This diagnosis's E3d/E3e/E4a/E4b
result is the first evidence that Cycles does **not** lose comparable energy
at roughness 0.85, i.e. that floor may have been tuned to Astroray's own
(incorrect) behaviour rather than to physically/Cycles-correct behaviour.

**Secondary, smaller effect:** a residual blue-channel skew (E0/E2b/E3e:
blue ~0.913-0.918 vs red ~0.943-0.946; E4b: blue 0.921 vs red 0.952) persists
even once the achromatic roughness effect is subtracted out (E5's spread
narrows to 1.5 percentage points but does not vanish). This is consistent
with — but not proven to be — the previously-logged spectral-upsampling
nonlinearity (memory `spectral-upsample-nonlinearity-scaled-bsdf`) acting on
the ground's own (0.25,0.27,0.24) colour, superimposed on the roughness
effect. It is roughly 5-10x smaller than the roughness effect and was not
chased further this session.

## Outstanding (not run this session — time-boxed)

- A numeric comparison of `DisneyEnergyCompensationTables::ggxE(roughness=0.85,
  mu)` / `ggxEavg(0.85)` against Cycles' own `microfacet_ggx_preserve_energy`
  LUT (or an independent Monte-Carlo directional-albedo estimate of a rough
  dielectric at the same roughness/view-angle) would confirm the exact
  mechanism and magnitude inside `ggxDirectionalAlbedo`/`layeringWeightAfter`,
  rather than the roughness-gating evidence recorded here.
- Whether the residual blue-channel skew (secondary effect above) is fully
  explained by spectral-upsampling nonlinearity or has its own separate
  cause was not isolated further (E5 narrows but does not close it).
- A distinguishing test at roughness values between 0 and 0.85 (e.g. 0.3,
  0.5 — matching the existing furnace test's tested value) was not run; it
  would show whether the loss is linear in roughness or has a threshold.

## Recommendation

- **Owning package: not pkg258.** Env NEE is cleared as a cause (E4). This
  belongs to whichever package owns `plugins/materials/principled.cpp`'s
  specular/diffuse energy-layering (GGX multiscatter compensation /
  `ggxDirectionalAlbedo` / `layeringWeightAfter`) — a materials/BSDF package,
  not a light-sampling one. Suggest filing a new, tightly-scoped follow-up
  package for the roughness-dependent diffuse-energy-loss bug rather than
  reopening pkg258.
- **Expected fix size:** likely more than the ~30-line ceiling this task is
  authorised to land directly — it requires either correcting the
  `ggxE`/`ggxEavg` LUT lookup/interpolation at high roughness or replacing
  `layeringWeightAfter`'s per-channel approximation with Cycles' actual
  scalar-max formula (`cite-algorithm` applies: Cycles `bsdf_util.h
  closure_layering_weight`), plus a **new** furnace/parity test at roughness
  0.85 (the existing one only covers 0.5) and a re-check of whether the
  existing `floor=0.85` tolerance in `test_principled_bsdf.py` /
  `test_pkg178_principled_gpu_furnace.py` needs re-deriving against Cycles
  rather than against Astroray's own white-Lambertian reference.
- **No fix landed in this diagnosis lane** (out of scope per brief and
  because root-causing the exact LUT/formula error needs the "Outstanding"
  numeric comparison above, not just the roughness-gating evidence).
- **Harness floor:** no change recommended to `HDRI_MIN_BACKGROUND_MEAN` —
  it already targets the sky ROI, which is unaffected by this finding.

## Incidental finding (out of scope, flagged separately)

While building the Sun-lamp control scenes (E4/E5), removing the World's
`TEX_ENVIRONMENT` node and leaving `World Output.Surface` unconnected reads
correctly as pure black (0.0) in Cycles but as a nonzero background
(sky_mean ≈ 0.150, all three channels) in Astroray — `blender_addon`'s
`setup_world` evidently falls back to a nonzero default when it finds no
recognised world-shader node, rather than treating "no shader" as black. This
did not affect any experiment above (worked around with an explicit
zero-strength `ShaderNodeBackground`) and does not affect `hdri_exterior_hair`
(which always has an Environment Texture node), but is a real, separate addon
bug worth its own follow-up.
