# pkg139 — Addon AREA-light orientation convention (emits +Z, Cycles emits −Z) + world strength-0 background skip

**Pillar:** 2 (Blender integration correctness)
**Track:** A (addon/CPU lane; parity-tested against headless Cycles — Blender 5.1 installed locally)
**Codex-paste-ready:** no (a sign/convention fix, but it must be validated against a live Cycles A/B render, not unit-tested in isolation)
**Status:** open — dispatchable now (independent of the pkg122 energy calibration in flight; do NOT conflate — see Non-goals)
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

- [ ] AREA basis flip (normal → local −Z) + non-square axis check.
- [ ] Strength-0 world background fix.
- [ ] Cycles A/B parity gates (identity + rotated + non-square).

## Lessons

*(Fill in after the package is done.)*
