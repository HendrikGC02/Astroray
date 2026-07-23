# pkg139 — Addon AREA-light orientation convention (emits +Z, Cycles emits −Z) + world strength-0 background skip

**Pillar:** 2 (Blender integration correctness)
**Track:** A (addon/CPU lane; parity-tested against headless Cycles — Blender 5.1 installed locally)
**Codex-paste-ready:** no (a sign/convention fix, but it must be validated against a live Cycles A/B render, not unit-tested in isolation)
**Status:** done (PR #505 merged 2026-07-21 as `ab959c5` — AREA -Z basis flip + world strength-0 black background; live-Cycles oracle rows 0.96–1.01 vs the pre-fix 0.089. The pkg139 oracle dataset is one leg of the pkg146 discrepancy investigation — keep `scripts/verify_pkg139_area_orientation_oracle.py` intact.)
**Estimated effort:** S (one-line basis flip + a small world-background guard fix + a parity test)
**Depends on:** none. Composes with pkg122 (energy) and pkg119-B (parity harness) but blocks on neither.

---

## Context — found by the pkg122 hardware verifier (2026-07-20 overnight)

While validating the pkg122 per-type energy derivations against a live Cycles
oracle, the verifier isolated an **orientation** bug that is independent of the
energy scaling: an artist-placed **default-rotation Blender area light points
AWAY from the scene in Astroray**. Evidence in the pkg122 worktree
(`Astroray-pkg122/test_results/`, script
`scripts/verify_pkg122_cycles_oracle.py`):

- Identity-rotation area light: Astroray/Cycles mean ratio **0.089–0.116×**
  (scene lit only by leakage/bounce — the exact pre-pkg122 "dim area light"
  symptom, reproduced through a **second, independent mechanism**).
- Same scene with the light flipped 180° about local X: ratio **1.07–1.09×**
  (normal, consistent with the post-#489 parity band).

This is likely a large chunk of the remaining owner-visible dimness in real
`.blend` scenes: every default-orientation area lamp faces backwards.

## Root cause (verified in code)

`blender_addon/__init__.py` `convert_lights()` AREA branch
(`__init__.py:3947-3968`):

```python
basis = matrix.to_3x3()
axis_u = list((basis @ mathutils.Vector((1, 0, 0))).normalized())   # local +X
axis_v = list((basis @ mathutils.Vector((0, 1, 0))).normalized())   # local +Y
```

The engine `AreaLight` emits along its normal `u × v` = local **+Z**. But
Blender/Cycles lights emit along local **−Z** — the same convention the addon
itself already uses for SUN (`__init__.py:3941`,
`matrix.to_3x3() @ Vector((0, 0, -1))`) and SPOT (`__init__.py:3971`). Only the
AREA branch got the sign wrong, so the emitting face points opposite to what
the artist sees in Blender.

## Fix plan (cite — no inventions, CLAUDE.md §6)

**Flip the basis so the implied normal is local −Z**, e.g.
`axis_v = basis @ Vector((0, -1, 0))` (u = +X, v = −Y ⇒ u×v = −Z), which is the
same 180°-about-local-X flip the verifier measured at 1.07–1.09×. Keep the
`size_x`/`size_y` mapping consistent with the chosen flip (u stays +X so
`size_x` still maps to u; verify the ELLIPSE/RECTANGLE non-square case renders
with the correct long axis, not mirrored).

**Cite:** Cycles Blender sync,
`intern/cycles/blender/light.cpp` (`BlenderSync::sync_light`, Apache-2.0 /
Blender GPL-compatible source tree — cite the convention, port no code):
`axisu` = transform X axis, `axisv` = transform Y axis, emission direction =
**−Z** of the light transform — the same convention as spot/sun/camera. In-repo
precedent: the addon's own SUN/SPOT branches (`__init__.py:3941, 3971`).

### Secondary (bounded, same file, verifier-evidenced): world strength-0 background skip

`setup_world()` (`__init__.py:4082-4086`) only calls
`renderer.set_background_color(...)` when `bg_color and strength > 0.01`. A
Blender world with **strength = 0.0** (artist intent: black background) is
silently skipped, leaving the **engine's built-in default background** visible
— the verifier saw it outside spot cones. Fix: when `bg_color` exists, always
call `set_background_color([c * strength for c in bg_color])` (strength 0 ⇒
explicit black), dropping the `strength > 0.01` guard. One line; test with a
strength-0 world (background must render black, not the engine default).

## Verification gates

- [ ] Headless-Blender parity A/B (reuse `verify_pkg122_cycles_oracle.py`
      methodology or `scripts/verify_pkg115_textures_blender.py` harness):
      default-rotation area light scene — Astroray/Cycles mean ratio moves from
      ~0.09–0.12× to the normal band (~0.9–1.1×; exact bound calibrated to the
      post-#489/pkg122 parity numbers at test time).
- [ ] Rotated (non-identity) area light agrees with Cycles — the flip must be
      convention-correct, not a compensating hack that only fixes identity.
- [ ] Non-square RECTANGLE/ELLIPSE case: long axis matches Cycles (no mirror /
      axis swap).
- [ ] Strength-0 world renders a black background (not the engine default).
- [ ] Existing addon light tests + pkg89 parity gates stay green.

## Non-goals

- **Not energy calibration** — that is pkg122 (in flight). This package fixes
  *direction*; magnitudes are pkg122's. Do not touch wattage→radiance factors.
- **Not Defect 4** (RGBIlluminant-vs-RGBUnbounded convention) — owner-reserved.
- **Not spread/shape sampling** — only the basis orientation + the world guard.

## Provenance

Filed from the **pkg122 hardware-verifier findings (2026-07-20 overnight)**:
measured identity-rotation ratio 0.089–0.116× vs Cycles, 180°-local-X flip →
1.07–1.09×; evidence in `Astroray-pkg122/test_results/` +
`scripts/verify_pkg122_cycles_oracle.py`. Code anchors verified in main
checkout: `blender_addon/__init__.py:3947-3968` (AREA basis), `:3941`/`:3971`
(SUN/SPOT already −Z), `:4082-4086` (strength guard).

## Progress

- [x] AREA basis flip (normal → local −Z) + non-square axis check (PR #505).
- [x] Strength-0 world background fix (PR #505).
- [x] Cycles A/B parity gates (identity + rotated + non-square) — convention
      verified live against headless Cycles on RTX 5070 Ti hardware
      (2026-07-21, PR #505). See Hardware verification section below.

## Lessons

### Hardware verification 2026-07-21

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 610.47, CUDA 12.8 (nvcc,
build_cuda/CMakeCache.txt), Windows 11 Enterprise 10.0.26200. Blender 5.1.0
(hash adfe2921d5f3, built 2026-03-17). PR #505 head
8f74fc067488af655b892e7e024dc4dedfa9c951, PYTHON-ONLY branch (blender_addon +
tests) off origin/main; verified against main's fresh build_cuda/Release
astroray.pyd (engine code identical between branch and main, per dispatch
instructions) via ASTRORAY_BUILD_DIR. Confirmed both module provenances at
render time: `astroray.__file__` resolved to
`Astroray/build_cuda/Release/astroray.cp313-win_amd64.pyd` (main, fresh --
built after main HEAD 2b18a1d 17:38:11, .pyd mtime 17:41:54/56) and
`blender_addon.__file__` resolved to
`Astroray-pkg139/blender_addon/__init__.py` (the PR's fixed addon, not
main's).

Live headless-Blender-vs-Cycles oracle
(`scripts/verify_pkg139_area_orientation_oracle.py`, adapted from
`Astroray-pkg122/scripts/verify_pkg122_cycles_oracle.py`), 128x128, 512 spp,
seed 7, `--background --factory-startup`:

| Scenario | Cycles mean RGB | Astroray mean RGB | Astroray/Cycles ratio | NaN px | Verdict |
|---|---|---|---|---|---|
| AREA identity rotation (3x3 rect, energy 300W, height 3m) | [1.2621999871730805, 1.2621999871730805, 1.2621999871730805] | [1.2447374701499938, 1.2453984093666077, 1.218624472618103] | [0.9861650156864626, 0.9866886563324225, 0.9654765370006282] | 0/0 | PASS -- within normal band, not the pre-fix 0.089-0.116x regime |
| AREA rotated 45 deg about local X | [1.111258443593979, 1.111258443593979, 1.111258443593979] | [1.0886146026849746, 1.0902422112226486, 1.0686646163463593] | [0.9796232451239959, 0.9810878985959732, 0.961670637921216] | 0/0 | PASS -- convention holds under non-identity rotation, not a compensating identity-only hack |
| AREA non-square rectangle (size_x=2.4, size_y=0.4), center patch | [1.5125463318824768 x3] | [1.5297622787952423, 1.5305179703235625, 1.4970408940315247] | [1.0113820955760997, 1.0118817110340803, 0.9897487848642267] | 0/0 | PASS |
| non-square, probe +X (u / size_x, long axis) | [0.8557976856827736 x3] | [0.8368318201974034, 0.8357639908790588, 0.8177063912153244] | [0.9778383772208512, 0.9765906181579219, 0.9554903044204202] | 0/0 | PASS -- brighter than +Y probe in both engines (long axis correctly along u) |
| non-square, probe +Y (v / size_y, short axis) | [0.7634025095030665 x3] | [0.7410957077518106, 0.7434861361980438, 0.7317604580894113] | [0.9707797636586544, 0.9739110455400688, 0.9585512871391364] | 0/0 | PASS -- no axis swap/mirror: X > Y ordering matches Cycles in both engines |
| World strength=0.0, SPOT-cone scene, corner patch outside cone | [0.0, 0.0, 0.0] | [0.0, 0.0, 0.0] | n/a (both exactly black) | 0/0 | PASS -- `Set background color: [0.0, 0.0, 0.0]` logged by the addon (guard removed, call now fires at strength 0); pre-fix this log line would not have printed at all and the engine default background would have leaked into the corner |

**Visual inspection:** read every PNG in
`Astroray-pkg139/test_results/pkg139_oracle/*_view.png`. Identity and
rotated45: Astroray and Cycles both show a bright, correctly-oriented lit
disc on the floor in matching positions -- no evidence of the light facing
away from the scene. Non-square: both engines show a saturated central
highlight (aspect-ratio elongation is clipped by overexposure at this
tonemap, not usable for the mirror check by eye -- relied on the quantitative
+X/+Y probes above instead, which agree on ordering). World-strength-zero:
both PNGs show a solid black frame with a small white spot-cone circle in
matching position/size -- no leaked background in either engine. No
fireflies, no banding, no magenta/black NaN pixels, no mode regressions
observed in any of the 8 renders (4 scenarios x 2 engines).

**Anomalies worth watching:** none blocking. `[CUDA] Scene uploaded: ...,
0 lights, ...` printed in every Astroray run despite the dedicated area/spot
light clearly contributing (ratios ~0.96-1.01x); this is a stats-line label
question (dedicated lights apparently not counted in that particular log
field), not a functional issue -- radiance output matches Cycles. Did not
rerun the full pytest suite or pkg89 parity gates in this session (per
dispatch scope: those were already verified green by the
team-lead/implementer -- 6 new convention unit tests + 71 addon-adjacent
tests, CI pending on the py-only branch); this session's gate was
specifically the live Cycles A/B pixel oracle the spec called out as still
open.

