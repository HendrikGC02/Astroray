# pkg265 Phase 3 — rough-glass method choice (CPU walk vs GPU single scatter)

Lane i14, batch i, 2026-10-06. Owner decision (2026-10-06): "port whichever is the more
physically accurate one that also looks best and nearly matches Cycles".
Evidence: `C:\Users\hgcom\OneDrive\Astroray\astra_run\batch-i\i14\` (scripts, `.npy`
legs, `furnace_table.md`, `glass_ab_table.md`, `glass_ab_contact_sheet.png`, `zoom_r100.png`).

## The three methods

| | Model | Energy at a single interface |
|---|---|---|
| Astroray CPU (`principled.cpp`, pkg265) | Heitz et al. 2016 multiple-scattering Smith random walk (DOI 10.1145/2897824.2925943), stochastic eval (§8.1) | Lossless by construction (R+T = 1) |
| Astroray GPU (`gpu_pr_chooseAndSampleDir` / `gpu_pr_transmissionEval`) | Single-scatter GGX + `gpu_ggxGlassCompensationFactor` on the **transmission** sub-lobe only + dead-sample → delta reroute (pkg264 #771) | Under-compensated: the factor is `1 + Fms·(1-E)/E` with `Fms` from the dielectric `Fss` (small), not `1/E` |
| Cycles 5.2 default | Single-scatter GGX × `energy_scale = 1/E` on reflection AND transmission (Turquin albedo scaling, `microfacet_ggx_preserve_energy`, glass E tables; `Fss` = transmission tint = 1 for clear glass) | Conserving per direction up to table resolution |

Blender 5.2 defaults (queried headless, `bl_defaults.py`): Principled BSDF and Glass BSDF both
default to `MULTI_GGX`. Since Blender 4.0 (PR #107958, "Remove MultiGGX code, replace with
albedo scaling") `MULTI_GGX` **is** the 1/E albedo scaling above; the old
`MICROFACET_MULTI_GGX_GLASS` random walk — the same Heitz 2016 model the Astroray CPU walk
implements — was removed for speed/noise, the release note conceding the "directional
distribution is no longer theoretically ideal". Neither Astroray backend reproduces Cycles'
current method: the CPU is Cycles' pre-4.0 model; the GPU is a weaker variant of its current one.

All Astroray GPU numbers use the #1111 Fresnel-side fix (build `6b8d03b8`), i.e. the
equal-footing comparison the lead asked for. CPU numbers: this branch (MinGW, OpenMP).

## (a) White furnace — clear glass sphere, uniform white field (linear, 80², 256 spp, depth 64)

Radiance invariance: every pixel must read 1.0. "rim" = the annulus 20–26 px of a 27.5 px
silhouette (grazing incidence, where single scatter loses most); "centre" = the 24² patch the
existing `test_pkg265_lit_furnace` reads.

| IOR | r | CPU walk centre/rim | GPU SS centre/rim | Cycles MULTI_GGX centre/rim | Cycles GGX centre/rim |
|---|---|---|---|---|---|
| 1.33 | 0.10 | 1.000 / 0.999 | 1.001 / 1.000 | 1.000 / 0.999 | 1.000 / 0.999 |
| 1.33 | 0.30 | 1.000 / 0.999 | 1.003 / 0.984 | 1.000 / 0.999 | 0.990 / 0.951 |
| 1.33 | 0.50 | 1.000 / 0.999 | 1.010 / 0.908 | 1.000 / 0.987 | 0.925 / 0.769 |
| 1.33 | 0.75 | 1.000 / 1.000 | 1.019 / 0.761 | 0.995 / 0.981 | 0.715 / 0.535 |
| 1.33 | 1.00 | 1.000 / 1.000 | 1.014 / 0.554 | 0.991 / 0.990 | 0.477 / 0.391 |
| 1.50 | 0.10 | 1.000 / 0.998 | 1.001 / 0.999 | 1.000 / 0.998 | 1.000 / 0.998 |
| 1.50 | 0.30 | 1.000 / 0.999 | 1.003 / 0.978 | 1.001 / 0.997 | 0.986 / 0.937 |
| 1.50 | 0.50 | 1.000 / 1.000 | 1.004 / 0.886 | 0.997 / 0.983 | 0.889 / 0.728 |
| 1.50 | 0.75 | 1.000 / 1.000 | 0.995 / 0.714 | 0.988 / 0.975 | 0.616 / 0.471 |
| 1.50 | 1.00 | 1.000 / 1.000 | 0.969 / 0.494 | 0.983 / 0.981 | 0.366 / 0.323 |
| 1.80 | 0.10 | 0.999 / 0.996 | 1.001 / 0.998 | 1.000 / 0.996 | 1.000 / 0.996 |
| 1.80 | 0.30 | 1.000 / 0.996 | 1.000 / 0.964 | 1.001 / 0.995 | 0.978 / 0.917 |
| 1.80 | 0.50 | 0.999 / 0.998 | 0.970 / 0.838 | 0.993 / 0.984 | 0.829 / 0.677 |
| 1.80 | 0.75 | 1.000 / 0.999 | 0.887 / 0.620 | 0.972 / 0.960 | 0.495 / 0.395 |
| 1.80 | 1.00 | 1.000 / 0.999 | 0.784 / 0.410 | 0.956 / 0.951 | 0.257 / 0.245 |

- CPU walk: 0.996–1.000 everywhere. Cycles MULTI_GGX: 0.951–1.001 (table-limited).
- GPU SS: centre in band at IOR ≤ 1.5 (why the lit-furnace gate now passes after #1111) but
  the rim loses **up to 51 % (IOR 1.5) / 59 % (IOR 1.8) at r 1.0**, and the centre GAINS
  up to +1.9 % at IOR 1.33. The centre-patch furnace is blind to grazing loss, exactly as
  i11 found for #1111. A lossless dielectric that darkens at the rim in a white furnace is
  the "dark ball" the owner reported (pkg263).

## (b) Rough glass sphere vs Cycles 5.2 (pkg263 scene, IOR 1.45, 256², 256 spp, via the addon)

Same `scenes.build_glass_scene` for every leg (`i14_leg.py`, `glass_ab.py`); ratios are
linear ROI means over Cycles MULTI_GGX (the 5.2 default). Background ROI = 1.000 in all
legs (calibration).

| r | ROI | Cycles MULTI (abs) | Cycles GGX / MULTI | **CPU walk** / MULTI | **GPU SS** / MULTI |
|---|---|---|---|---|---|
| 0.20 | centre | 0.1803 | 0.998 | 0.988 | 0.991 |
| 0.20 | limb | 0.3165 | 0.992 | 0.879 | 0.891 |
| 0.50 | centre | 0.2204 | 0.902 | 1.110 | 0.994 |
| 0.50 | limb | 0.4284 | 0.707 | 1.057 | 1.135 |
| 0.85 | centre | 0.2914 | 0.519 | 1.635 | 0.926 |
| 0.85 | limb | 0.5086 | 0.376 | 1.153 | 1.105 |
| 1.00 | centre | 0.3013 | 0.386 | 1.717 | 0.891 |
| 1.00 | limb | 0.5808 | 0.320 | 1.025 | 0.860 |

Shape metric (relative RMSE of 8×8-binned luminance over the sphere disc vs Cycles MULTI):

| r | Cycles GGX | CPU walk | GPU SS |
|---|---|---|---|
| 0.20 | 0.004 | 0.124 | 0.117 |
| 0.50 | 0.221 | 0.123 | 0.188 |
| 0.85 | 0.586 | 0.461 | 0.318 |
| 1.00 | 0.694 | 0.568 | 0.503 |

- r ≤ 0.5: both methods are within ~±13 % of Cycles; the walk is closer at r 0.5 (RMSE 0.12
  vs 0.19). The r 0.2 limb (0.88) is shared by both backends, so it is not the method
  (the known pkg264 §7.1 addon-side limb residual).
- r ≥ 0.85: **neither nearly matches Cycles.** The walk is +64–72 % at the centre — the
  divergence pkg265 Phase 11 already validated as physical with an independent
  explicit-heightfield oracle and an independent numpy sphere tracer (MS/SS = 1.608 vs the
  engine's 1.610). The GPU's centre (0.89–0.93) is closer only because its grazing energy
  loss (table a) happens to offset the multiple-scattering redistribution; its limb and
  shape are no better.

## (c) Visual (contact sheet, `zoom_r100.png`, inspected)

Columns: Cycles MULTI_GGX | Cycles GGX | CPU walk | GPU SS; rows r 0.2/0.5/0.85/1.0.
- r 0.2/0.5: all four read as the same frosted-glass ball; the walk and Cycles MULTI are
  the closest pair at r 0.5.
- r 0.85/1.0: Cycles MULTI has a bright upper-right rim (the key light at grazing
  reflection — Phase-1 table: 1/E over-counts grazing reflection ~5.5× vs the walk at
  r 1.0 μ 0.1) and a soft lit-side gradient. The walk is a bright, nearly uniform
  translucent ball (multiple scattering diffuses the light), with less form. The GPU shows
  a darker interior band and a bright lower-left limb, with blotchy noise near the
  highlight — visibly the single-scatter loss, not a Cycles look. Cycles GGX (no
  compensation) is the dark ball.

## Recommendation

**The CPU Heitz walk.** It is the only method that conserves energy across the whole
grid (incl. the rim), is validated against independent ground truth (Phase 11), is the
model Cycles itself shipped until 4.0, and fixes the owner's "dark ball". It matches
Cycles within ~12 % up to r 0.5; above that Cycles' 1/E is the approximation (owner
physics-first rule 2026-09-08 and 2026-09-29: keep physics where Cycles differs). The GPU
single-scatter method fails the white furnace by up to 59 % at the rim; its closer
high-roughness centre number is coincidental and should not decide the choice.

Owner-level caveat: if "nearly matches Cycles" at r ≥ 0.85 outranks physics, the only
method that does is Cycles' own 1/E albedo scaling on both lobes, which pkg265's
non-goal ("do not port Cycles' energy_scale tables as the mechanism") and the owner's
physics-first rule exclude. That is a decision for the owner, not this lane.

## Implementation status (this lane): not ported

The winner is already on the CPU; the GPU lacks it. The GPU walk was **not** implemented
here. It is the multi-part, register-sensitive port specified in
`pkg265-multiscatter-microfacet-research.md` §"Phase 3 (GPU walk) — port design":
a device walk (`gpu_msd_sampleWalk`, ~250 lines of `microsurface_dielectric.h` with
`erfinvf`/`erff`, height sampling, VNDF), a device stochastic eval wired into the closure
graph eval + spectral eval (the sample/eval re-eval trap the CPU Phase 10 hit), a
`__constant__` runtime flag + host upload, and the mixture-pdf rewrite of
`gpu_principled_sample`. None of it can be compiled or validated in a CPU-only lane, and
each iteration needs a lead CUDA build + cuobjdump. Expected register impact if done per
the design: the walk/eval as `__noinline__` callees behind the runtime flag keep
`stageShadeBucketedKernel` at REG 254 (the call boundary isolates the walk's loop state);
STACK grows by the callee frames (estimate 100–300 B per thread); inlining it would
spill. Gates for that lane: the rim furnace (table a) on GPU in [0.97, 1.02], the CPU/GPU
glass-sphere ROI parity ±5 %, `test_pkg188[coat_over_tinted_glass]` (the CPU/GPU divergence
that only closes when GPU walks too), cuobjdump REG/STACK on every shade specialisation.
