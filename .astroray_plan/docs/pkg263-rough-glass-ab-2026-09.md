# pkg263 — Rough-glass Cycles A/B (Astroray CPU vs Blender 5.2 Cycles CPU)

**Date:** 2026-09-08
**Oracle:** Blender 5.2 LTS Cycles, CPU, seed 7 (+ a second seed 1234 run for
the noise floor), 128 spp.
**Astroray leg:** native `principled` translation of a `ShaderNodeBsdfGlass`
(Color=white, IOR 1.45, Roughness swept), CPU, 128 spp, via the real addon
Blender→native translation (`blender_addon/__init__.py` `BSDF_GLASS` branch:
`transmission=1.0, ior=1.45, roughness=r`).
**Scene:** `benchmarks/cycles-parity/metal_ab/scenes.py` `build_glass_scene` —
a glass sphere (radius 0.6) lifted 0.05 above a grey diffuse plane, one area
light (energy 150, size 1.0) + a uniform grey world (colour 0.6, strength 0.3)
so the limb sees both direct and environment light. Camera axis passes
through the sphere centre (required for the analytic ROI geometry below).
Linear EXR both engines, Standard view transform, exposure 0, adaptive
sampling off, denoise off on the scene AND the view layer, res 256×256.
**Harness:** `benchmarks/cycles-parity/metal_ab/harness.py --material glass`
(pkg129 driver, extended — no new harness). Report:
`test_results/pkg263_rough_glass_ab/`.

**GPU leg:** not run (lane was CPU-only, no GPU lock taken; optional per the
spec).

## Verdict — limb darkening CONFIRMED, magnitude quantified, well outside noise

Astroray's rough-glass sphere is measurably dimmer than Cycles' at every
roughness, and the deficit is **worst at the limb (grazing) and grows sharply
with roughness** — exactly the owner's report. The effect is present even at
roughness 0 (a smaller, Fresnel/TIR-flavoured deficit) and compounds badly
once the rough transmission lobe engages.

The **noise floor** (Cycles rendered twice, seed 7 vs seed 1234, everything
else identical) is ≤1.4% on every ROI/roughness cell — 15-70× smaller than the
observed Astroray/Cycles gaps (19-66%). This is not sampling noise.

### Per-ROI Astroray/Cycles ratio (linear per-channel mean; R/G/B)

| r | centre disc (r<0.35R) | limb annulus (0.8R-0.98R) | background |
|---|---|---|---|
| 0.00 | 0.9633 / 0.9634 / 0.9490 | 0.8145 / 0.8169 / 0.7997 | 0.9990 / 1.0023 / 0.9797 |
| 0.20 | 0.9498 / 0.9517 / 0.9348 | 0.6728 / 0.6744 / 0.6615 | 0.9990 / 1.0023 / 0.9797 |
| 0.50 | 0.8092 / 0.8129 / 0.7910 | 0.4428 / 0.4446 / 0.4344 | 0.9990 / 1.0023 / 0.9797 |
| 0.85 | 0.5252 / 0.5259 / 0.5164 | 0.3415 / 0.3443 / 0.3313 | 0.9990 / 1.0023 / 0.9797 |

The background ROI (pure world sky, no glass in the pixel) is essentially
engine-identical at every roughness (ratio pinned to ~1.00/1.00/0.98,
roughness-independent as it must be) — this is the calibration check: the
color pipeline, exposure, and world-sampling match between engines, so the
centre/limb deficits above are specific to the glass BSDF, not a global
scale/colorspace bug.

### Raw per-ROI means (Cycles / Astroray, linear R/G/B)

| r | ROI | Cycles | Astroray |
|---|---|---|---|
| 0.00 | centre | 0.1773/0.1773/0.1773 | 0.1708/0.1708/0.1682 |
| 0.00 | limb | 0.2842/0.2842/0.2842 | 0.2315/0.2322/0.2273 |
| 0.00 | background | 0.1800/0.1800/0.1800 | 0.1798/0.1804/0.1763 |
| 0.20 | centre | 0.1801/0.1801/0.1801 | 0.1710/0.1714/0.1683 |
| 0.20 | limb | 0.3139/0.3139/0.3139 | 0.2112/0.2117/0.2077 |
| 0.20 | background | 0.1800/0.1800/0.1800 | 0.1798/0.1804/0.1763 |
| 0.50 | centre | 0.2225/0.2225/0.2225 | 0.1801/0.1809/0.1760 |
| 0.50 | limb | 0.4271/0.4271/0.4271 | 0.1891/0.1899/0.1855 |
| 0.50 | background | 0.1800/0.1800/0.1800 | 0.1798/0.1804/0.1763 |
| 0.85 | centre | 0.2917/0.2917/0.2917 | 0.1532/0.1534/0.1506 |
| 0.85 | limb | 0.5099/0.5099/0.5099 | 0.1741/0.1756/0.1690 |
| 0.85 | background | 0.1800/0.1800/0.1800 | 0.1798/0.1804/0.1763 |

### Limb/centre ratio per engine (self-referential — is the limb brighter than
the centre AT ALL, in each engine on its own?)

| r | Cycles limb/centre | Astroray limb/centre | (Astroray÷Cycles) of that ratio |
|---|---|---|---|
| 0.00 | 1.6034/1.6034/1.6034 | 1.3558/1.3596/1.3511 | 0.85× |
| 0.20 | 1.7431/1.7431/1.7431 | 1.2348/1.2353/1.2335 | 0.71× |
| 0.50 | 1.9192/1.9192/1.9192 | 1.0503/1.0496/1.0539 | 0.55× |
| 0.85 | 1.7482/1.7482/1.7482 | 1.1366/1.1444/1.1218 | 0.65× |

Both engines show the classic dielectric behaviour of the limb being
*brighter* than the centre (Fresnel reflectance rising toward grazing) — the
limb/centre ratio is >1 for both, at every roughness. What the owner is
seeing as "limb darkening" is this ratio being **systematically weaker in
Astroray** (0.55-0.85× of Cycles' own limb/centre ratio): Astroray's edge
brightening under-shoots Cycles', so next to a Cycles render the Astroray
limb reads comparatively flat/dark. The under-shoot is worst at r=0.5 (0.55×)
and partially recovers at r=0.85 (0.65×) — at very high roughness the
Fresnel-edge feature itself softens in both engines (the diffuse-like rough
lobe increasingly dominates over the specular grazing peak), narrowing the
relative gap even though the absolute energy deficit (previous table) keeps
growing.

### Noise floor — Cycles seed 7 vs seed 1234 (same scene, same spp, different RNG stream)

| r | ROI | ratio (seed7 / seed1234) |
|---|---|---|
| 0.00 | centre | 1.0003/1.0003/1.0003 |
| 0.00 | limb | 1.0040/1.0040/1.0040 |
| 0.00 | background | 1.0000/1.0000/1.0000 |
| 0.20 | centre | 0.9999/0.9999/0.9999 |
| 0.20 | limb | 0.9933/0.9933/0.9933 |
| 0.20 | background | 1.0000/1.0000/1.0000 |
| 0.50 | centre | 1.0137/1.0137/1.0137 |
| 0.50 | limb | 1.0004/1.0004/1.0004 |
| 0.50 | background | 1.0000/1.0000/1.0000 |
| 0.85 | centre | 0.9975/0.9975/0.9975 |
| 0.85 | limb | 1.0004/1.0004/1.0004 |
| 0.85 | background | 1.0000/1.0000/1.0000 |

Max deviation from 1.0 across every cell: **1.37%** (r=0.5 centre). The
smallest observed Astroray/Cycles deficit above is 19% (r=0 background is a
wash, but the smallest GLASS-ROI deficit is centre r=0 at 3.7-5.1%, still
~3× the noise floor; every limb cell and every centre cell at r≥0.2 is
10-60× the noise floor). The effect is real.

## Root-cause leads (data-driven, no engine change made here)

1. **Present at roughness 0 → Fresnel/TIR handling at grazing incidence.**
   Even for perfectly smooth glass, the limb ratio (0.81) is already well
   below the centre ratio (0.96). A smooth dielectric's grazing behaviour is
   governed purely by the Fresnel term (`plugins/materials/disney.cpp` /
   `principled.cpp`'s dielectric Fresnel + TIR path, `ggxGlassComp`) — the
   deficit growing toward the silhouette at r=0 with no microfacet roughness
   involved points at that grazing/TIR evaluation, not at the GGX sampling
   machinery. This is squarely pkg124's territory (VNDF reflection lobe —
   the spec explicitly asks for this measurement to steer it).

2. **Grows sharply with roughness → energy loss in the rough transmission
   lobe at grazing.** The centre-ROI deficit alone goes from 3.7% (r=0) to
   47% (r=0.85); the limb deficit from 19% to 66% over the same sweep, and
   the whole-sphere contact sheets (`.astroray_plan/docs/pkg263/
   glass_r050__contact_sheet.png`, `glass_r085__contact_sheet.png`) show the
   Astroray sphere visibly dimmer over its ENTIRE silhouette at r≥0.5, not
   only at the rim — i.e. above r≈0.5 this is no longer a purely
   grazing/limb phenomenon, it is a global energy deficit in the rough
   dielectric lobe that is simply *worse* at grazing. This matches pkg179
   Phase 2's still-open boxes (dead-sample redistribution; furnace in-band
   checks at r∈{0.3,0.6,1.0} were never completed for CPU or GPU) — a
   masked/discarded dead-sample fraction in the rough transmission path
   would show up exactly this way: worse with roughness, worst at grazing
   angles where more samples miss/TIR out.

3. **Non-monotonic limb/centre relative gap (0.85× → 0.71× → 0.55× →
   0.65×)** is a secondary, more speculative observation: the *absolute*
   deficit keeps growing through r=0.85, but the *relative* Fresnel-edge
   under-shoot peaks at r=0.5 and eases back at r=0.85. This is consistent
   with a rough Fresnel-edge term that Astroray under-weights specifically
   in the roughness range where microfacet spread first starts competing
   with the specular grazing peak, but this run doesn't isolate a mechanism
   for it — flagging it for whoever picks up lead 1/2, not asserting a cause.

## Visual evidence

Per roughness, `.astroray_plan/docs/pkg263/<config>__contact_sheet.png`
(Cycles | Astroray | abs-diff ×3, all sRGB display for viewing only — every
number above was computed on the LINEAR arrays) and
`<config>__cycles_roi.png` / `<config>__astroray_roi.png` (the three ROIs
drawn on each engine's own render: red = centre disc, green = limb annulus
inner+outer bound, blue = background patch).

- `glass_r000__contact_sheet.png` — r=0: Cycles and Astroray look close at a
  glance (both show correct refraction, the horizon line, and a caustic on
  the plane); the abs-diff panel concentrates almost entirely on the sphere's
  silhouette rim, matching the limb-only deficit at this roughness.
- `glass_r050__contact_sheet.png` — r=0.5: Astroray's sphere is visibly
  darker/flatter than Cycles' bright, milky-looking rough-refraction sphere;
  the abs-diff panel is bright over the whole silhouette, not just the rim.
- `glass_r085__contact_sheet.png` — r=0.85: Cycles renders a near-white
  diffuse-looking sphere; Astroray's is markedly grey/dim by comparison — the
  largest, most visually obvious gap in the sweep.

## Files

- `benchmarks/cycles-parity/metal_ab/scenes.py` — `build_glass_scene`,
  `glass_sweep`, `sphere_projected_radius_px` (new).
- `benchmarks/cycles-parity/metal_ab/harness.py` — `run_glass`, `_roi_masks`,
  `write_glass_reports`, `--material glass` dispatch (new); also fixed a
  pre-existing bug in `render_leg.py`'s `_configure_render` that left the
  Astroray leg at Blender's factory-default 4096 samples with denoising ON
  (pkg176 Stage 4 retired the `custom_raytracer.samples`/`use_denoising`
  duplicates in favour of native `scene.cycles.*` for BOTH engines; the old
  code only wrote those for `engine == "CYCLES"`). Flagged as a follow-up
  (task_bb42ba06) since `blender_parity/render_leg.py` and
  `thin_film/render_leg.py` have the identical stale pattern, not touched
  here (out of scope for pkg263).
- `benchmarks/cycles-parity/metal_ab/render_leg.py` — `--material glass`
  dispatch, top-down pixel flip for the glass leg, `--seed` override (used
  for the noise-floor run above).
- `tests/test_pkg129_metal_ab_harness.py` — 6 new pure tests for the glass
  sweep, ROI geometry, ROI metrics, and report writer (13/13 green).
- `test_results/pkg263_rough_glass_ab/` — full sweep output (`.npy`,
  `glass_ab_report.json/.md`, all PNGs).
- `.astroray_plan/docs/pkg263/` — the 12 evidence PNGs referenced above
  (`git add -f`, global `*.png` ignore).

## Non-goals reaffirmed

No BSDF/engine change in this package. The leads above are for pkg124 and a
pkg179 Phase 2 follow-up to pick up.
