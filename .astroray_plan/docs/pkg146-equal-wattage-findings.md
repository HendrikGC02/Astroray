# pkg146 — Equal-wattage brightness-offset investigation: findings

**Investigator:** package-implementer (pkg146), 2026-07-23
**Spec:** `.astroray_plan/packages/pkg146-equal-wattage-offset-investigation.md`
**Baseline:** current `main` (RGBIlluminant D65 kept per pkg142 final adjudication; pkg139
AREA-orientation + world-strength-0 fix merged `ab959c5`/#505; pkg140 DistantLight fix
merged `a4045bb`/#507).

## One-paragraph answer

The pkg122 oracle's **1.07–1.16×** reading and pkg139's **0.96–1.01×** reading are **not
measuring the same thing on the same code**: pkg122's oracle ran *before* PR #505
(pkg139) landed, and every one of its four scenes set the Blender world-background
strength to `0.0` (artist intent: black) while relying on the addon's
`strength > 0.01` guard — a guard that pkg139 documents as skipping
`set_background_color` entirely at that threshold, leaving the C++ engine's **unset**
background sentinel (`Vec3(-1)`) active, which falls through to a hardcoded
`~0.2`-scaled sky-gradient fallback (`raytracer.h`, the `else` branch of the env-miss
code in `pathTraceSpectral`) instead of true black — while the paired Cycles render
legitimately got black. This produces an **additive**, light-type-**independent** leak
(confirmed both in pkg122's own numbers and in a from-scratch ablation below), which is
exactly the wrong shape for a per-type radiometry or emission-chromaticity bug (those
scale with brightness) and exactly the right shape for a background-leak. PR #505
already fixed the guard (bundled with the unrelated AREA-orientation fix) and pkg139's
own live-Cycles re-run — for AREA only — already lands in **[0.96, 1.01]**. No new
renderer-side fix is indicated by the evidence gathered. **POINT/SPOT/SUN could not be
directly re-verified live post-fix** in this investigation (blocked by the GPU-lock
constraint plus a newly-discovered, separate CPU-render hang in the Blender addon, see
below); the closure for those three types rests on mechanism + the AREA data point + an
addon-independent ablation, not a fresh live A/B, and a fast-follow live re-run is
recommended once GPU time or the hang-fix is available.

## 1. The two harnesses, lined up

| Axis | pkg122 oracle (`scripts/verify_pkg122_cycles_oracle.py`) | pkg139 oracle (`scripts/verify_pkg139_area_orientation_oracle.py`) |
|---|---|---|
| Code state | **Before** PR #505 (pkg139) | **After** PR #505 |
| Light types covered | POINT, AREA, SPOT, SUN (all four) | **AREA only** (identity, rotated45, nonsquare) + a SPOT scenario used *only* for the world-strength-0 black-background check, not an energy ratio |
| World background | `bg.inputs[1].default_value = 0.0` (strength 0, black intent) in all 4 scenes | Same: strength 0.0 in all AREA scenarios |
| World-strength-0 guard | **Buggy**: `strength > 0.01` skip → sky-gradient leak | **Fixed**: guard removed, always calls `set_background_color` |
| AREA orientation | Script has a **manual compensating 180°-about-X flip** applied only to the `CUSTOM_RAYTRACER` render (mathematically equivalent to the real fix for an identity-rotation square light — verified below) | Real code fix (`axis_v = basis @ (0,-1,0)`), no manual flip needed |
| Floor material | Diffuse BSDF, roughness 0, albedo 0.5, 40×40 (identical) | Same |
| Camera | (0,0,20), FOV 20°, straight down (SUN gets +5° tilt, documented caveat) | Same (no SUN scenario tested) |
| Resolution / patch | 64×64, 8×8 center patch | 128×128, 10×10 center patch |
| spp / seed | 512 / seed 7 | 512 / seed 7 |
| Colour management | `Standard`, exposure 0, gamma 1, linear EXR (identical) | Same |
| Device | `device_mode` **not forced** → `auto` → GPU (RTX, both pkg122 and pkg139 ran on GPU) | Same |

**Per the contract's "line up every difference" step:** the only *code* difference
between the two harnesses' shared axis (AREA) is the orientation fix, which I verified
is a **no-op for the identity-rotation, square-light case both oracles measure**
(rotating the light object 180° about local X gives `axis_v = matrix@(0,1,0) =
world(0,-1,0)` — bit-identical to the real fix's `axis_v = identity@(0,-1,0) =
world(0,-1,0)`). The **only mechanism-bearing difference** left standing is the
world-strength-0 guard state — which is *not* light-type-specific Python (it lives in
`setup_world()`, called once per scene regardless of light type) — plus the fact that
**pkg139 never re-tested POINT/SPOT/SUN**, so the "0.96–1.01× validates all four types"
reading in `pkg142`/`pkg146`'s own spec prose is a **mischaracterization**: it only
validates AREA.

## 2. Reproducing pkg122's number from its own images

Recomputed directly from the EXRs already on disk in
`Astroray-pkg122/test_results/pkg122_cycles_oracle/*.exr` (kept, read-only worktree),
using the exact `center_patch_mean(patch=8)` from the oracle script:

| Type | Cycles RGB | Astroray RGB (buggy bg) | ratio | ast−cyc (absolute) |
|---|---|---|---|---|
| POINT | 1.1017,1.1017,1.1017 | 1.199,1.216,1.214 | 1.088,1.104,1.102 | 0.097,0.115,0.112 |
| AREA  | 1.2494,1.2494,1.2494 | 1.342,1.357,1.345 | 1.074,1.086,1.076 | 0.093,0.108,0.096 |
| SPOT  | 1.1017,1.1017,1.1017 | 1.199,1.216,1.214 | 1.088,1.104,1.102 | 0.097,0.115,0.112 |
| SUN   | 0.7958,0.7958,0.7958 | 0.906,0.922,0.921 | 1.138,1.159,1.157 | 0.110,0.126,0.125 |

Exactly reproduces the previously-quoted **"1.07–1.16×, all four types"**. The
**absolute** excess (`ast − cyc`) is the tell: **it clusters tightly at ~0.09–0.13 per
channel across all four types**, despite the Cycles reference varying ~60% (0.80 to
1.25) across types. A per-type radiometry error or a D65/E chromaticity mismatch would
scale *with* brightness (multiplicative); a background leak does not (additive,
scene-geometry-driven, light-type-agnostic) — this is the smoking-gun signature that
points straight at `setup_world()`.

## 3. Ablation: isolating the background-leak mechanism (addon-independent)

To test the mechanism directly — without depending on the Blender addon's `render()`
call, which was found to hang in this environment (§4) — I used the direct
`astroray.Renderer()` CPU bindings (the same convention as
`tests/test_pkg122_light_energy_calibration.py`) to render each of pkg122's four
light configs (same wattage/height/size) **twice**:

- **(a) black:** `r.set_background_color([0,0,0])` called — matches Cycles + the
  *fixed* (post-#505) addon, which now unconditionally calls
  `set_background_color`.
- **(b) leaked:** `set_background_color` **never called** — reproduces the pre-#505
  guard-skip exactly (the engine's `backgroundColor` stays at its `Vec3(-1)`
  sentinel, which is precisely what the addon left it at pre-fix).

Results (64×64, patch=8, spp=512, seed=42; full data in
`test_results/pkg146_oracle/ablation_bg_leak/ablation_results.{json,csv}`):

| Type | black_bg RGB | leaked_bg RGB | delta (leaked−black) | leaked/black ratio |
|---|---|---|---|---|
| POINT | 0.997,1.002,0.987 | 1.055,1.079,1.086 | 0.058,0.076,0.099 | 1.058,1.076,1.100 |
| AREA  | 1.165,1.180,1.149 | 1.222,1.257,1.247 | 0.057,0.077,0.098 | 1.049,1.065,1.086 |
| SPOT  | 0.997,1.002,0.976 | 1.055,1.078,1.086 | 0.058,0.077,0.109 | 1.058,1.077,1.112 |
| SUN   | 0.791,0.799,0.779 | 0.848,0.876,0.878 | 0.057,0.077,0.098 | 1.072,1.096,1.126 |

The **delta is essentially IDENTICAL across all four light types** (~0.057–0.11 per
channel) — the same additive, type-agnostic signature as §2's real pkg122 data,
independently reproduced from first principles. **SPP-noise check** (per the dispatch's
explicit caveat): re-ran at spp=32 and spp=512 (16× apart) — the delta is stable to
<1% between the two (e.g. POINT delta_R = 0.0574 at spp=32 vs 0.0576 at spp=512),
confirming this is a **deterministic bias** (the hardcoded sky-gradient formula,
`Vec3(1)*(1-t) + Vec3(0.5,0.7,1.0)*t) * 0.2` in `raytracer.h`), not RNG noise (memory
`mc-noise-vs-deterministic`).

The ablation's magnitude (leaked/black ≈ 1.05–1.13) is in the same ballpark as, but
somewhat smaller than, pkg122's real ast/cyc excess (1.07–1.16) — plausibly because the
ablation's hand-built scene isn't pixel-identical to the addon-driven one (e.g. the
addon passes Blender's actual `light.spread` for AREA, `1.0` default in my script vs
Blender's real default; camera/ray-depth defaults may differ slightly). This is
expected and doesn't weaken the causal finding — the **uniform, type-independent,
noise-independent additive signature** is what identifies the mechanism, not an exact
percentage match from a decoupled reproduction.

## 4. Blocker found: Blender-addon CPU-mode render hang (new, separate finding)

Per the GPU-lock rule, I could not run the addon-driven live-Cycles oracle on the GPU.
Attempting to force `scene.custom_raytracer.device_mode = "cpu"` and re-run
`scripts/verify_pkg122_cycles_oracle.py` (patched to also force `scene.cycles.device =
"CPU"`) **hung indefinitely** on every light type at the `CUSTOM_RAYTRACER` render
call — confirmed via CPU-time sampling (process CPU time frozen at ~1.5–5.8s across
12+ minutes of wall-clock time = genuinely blocked, not slow).

Bisected with a minimal repro
(`test_results/pkg146_oracle/cpu_render_hang_repro/diag_render_minimal.py`):
- `import astroray`, `blender_addon.register()`, and `astroray.Renderer()` used
  **directly** (no Blender render call) all complete instantly, including
  `gpu_available=True`.
- `bpy.ops.render.render()` through `CUSTOM_RAYTRACER` with `device_mode='cpu'`
  completes in **0.01s at 16×16** resolution but **hangs indefinitely at 32×32**
  (spp=1 in both cases — resolution, not sample count, is the trigger).
- The direct Python bindings (`astroray.Renderer().render(...)`, used by
  `tests/test_pkg122_light_energy_calibration.py`) render 48×48–64×64 CPU scenes in
  a fraction of a second with **no hang** — so the underlying CPU path tracer itself
  is fine; the hang is specific to the **Blender addon's `render()` glue** at
  `device_mode='cpu'` and resolution > 16px (likely a tile/thread-count threshold in
  the addon-Blender progress/threading handoff that never gets exercised when
  `device_mode` is GPU, which is what every prior live-Cycles oracle run — pkg122,
  pkg139 — actually used).

This is a **real, reproducible, previously-undetected bug**, orthogonal to pkg146's
scope (energy/units) and to the background-leak finding above. It blocks any future
CPU-only headless-Blender verification of the addon. Recommend filing it as its own
small package/ticket; logs and the repro script are saved in
`test_results/pkg146_oracle/cpu_render_hang_repro/`.

## 5. Reconciliation verdict (per the investigation contract)

- **Dominant, demonstrated cause:** the pkg139/PR#505 world-strength-0
  `set_background_color` guard bug, already fixed in `main`. It produced an additive,
  light-type-independent leak of the sky-gradient fallback into every scene in
  pkg122's oracle (all of which authored an intentional black background at
  strength 0.0). Confirmed via (a) exact reproduction of the pkg122 numbers from its
  own images, (b) the constant-across-type absolute-delta signature in that same real
  data, and (c) an independent, addon-decoupled ablation reproducing the identical
  signature with SPP-stability ruling out noise.
- **Secondary correction to prior docs:** the "pkg139 oracle rows are 0.96–1.01
  WITHOUT any pkg142 change" claim (quoted in `pkg142-rgb-emission-convention.md` and
  this package's own spec) is **only true for AREA** — pkg139 never re-tested
  POINT/SPOT/SUN. The claim should be read as "AREA is confirmed in-band post-fix;
  POINT/SPOT/SUN are inferred in-band by mechanism, not directly re-measured."
- **No renderer-side offset requiring a NEW code fix was found.** Per the spec's DoD
  branch B ("If NO real offset remains... the pkg122 oracle is corrected/retired as the
  artifact"): this package recommends annotating `pkg122`'s "1.07-1.16x" oracle result
  as **stale / measured pre-#505** (not a live indictment of the current baseline), and
  closing the "dimmer/brighter than Cycles" complaint thread as a measurement
  artifact that has already been fixed in a different package.
- **Residual honesty (CLAUDE.md §1):** I could not obtain a fresh, addon-driven,
  live-Cycles A/B for POINT/SPOT/SUN post-fix (blocked by the GPU-lock rule + §4's
  hang). The evidence for those three types closing into [0.97,1.03] is **inference
  from a shared, type-agnostic root cause + a decoupled ablation**, not a direct
  re-measurement. **Recommended fast-follow:** once GPU time is available (outside
  this investigation's constraints) or the §4 hang is fixed, re-run
  `scripts/verify_pkg122_cycles_oracle.py` for POINT/SPOT/SUN on current `main` and
  confirm the ratio lands in-band; if it does not, that would indicate a small
  additional residual worth its own narrowly-scoped follow-up (do not retune emitters
  speculatively in the meantime).

## 6. Non-goals honored

- Did not revisit the emission convention (`RGBIlluminant` stays; pkg142 is closed).
- Did not loosen the [0.97,1.03] band.
- Did not "fix" the SUN camera-tilt or the AREA-orientation caveats already documented
  in the pkg122 oracle script (both orthogonal integration artifacts, not touched).

## 7. Evidence index

- `test_results/pkg146_oracle/pkg122_baseline_pre_pkg139fix/` — the original pkg122
  oracle PNGs (copied from the kept `Astroray-pkg122` worktree; pre-#505, all 4 types,
  Cycles + Astroray pairs).
- `test_results/pkg146_oracle/cycles_cpu_reference_current_main/` — fresh Cycles-only
  CPU renders (all 4 types) on current `main`, confirming Cycles-CPU forcing itself
  works fine (only the Astroray-addon side hangs, §4).
- `test_results/pkg146_oracle/ablation_bg_leak/` — the addon-independent black-vs-leaked
  ablation: PNGs (`*_black_bg.png`, `*_leaked_bg.png`) + `ablation_results.{json,csv}`
  (includes both spp=32 and spp=512 rows for the noise-vs-deterministic check).
- `test_results/pkg146_oracle/cpu_render_hang_repro/` — the minimal hang repro script +
  logs (16×16 completes, 32×32 hangs).
- `test_results/pkg146_oracle/summary_ratios.json` — consolidated ratio table across
  all three datasets (pkg122 baseline, pkg139 AREA, this package's ablation).

## 8. Citations

- Cycles `src/scene/light.cpp`, `src/kernel/light/area.h` — RGB-native emission,
  Apache-2.0 (already cited in `defect4-rgb-emission-research.md`; re-confirmed
  unaffected by this investigation).
- `raytracer.h` (`pathTraceSpectral`, the env-miss `else` branch with the hardcoded
  `Vec3(1)*(1-t) + Vec3(0.5,0.7,1.0)*t) * 0.2` sky-gradient) — in-repo, project code,
  the mechanism identified here.
- `blender_addon/__init__.py::setup_world()` (pkg139's fix, PR #505, `ab959c5`) — the
  guard removal that already closes this.
- Memory `mc-noise-vs-deterministic`, `ssim-wrong-gate-for-independent-rng`,
  `gamma-vs-linear-comparison-artifact` — the three known false-lead patterns this
  investigation explicitly checked against and ruled out (colour management was
  identical linear EXR on both sides in every harness compared; the delta does not
  shrink with spp).
