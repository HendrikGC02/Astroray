# pkg256 — Sky texture node (`ShaderNodeTexSky`)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 1 week
**Depends on:** pkg63, pkg229

---

## Goal

Before: `ShaderNodeTexSky` is never referenced anywhere in
`blender_addon/__init__.py` — a World using it silently falls through
`setup_world`'s `TEX_ENVIRONMENT`/`BACKGROUND` walk to the flat solid-color
fallback, with no warning (all 14 sockets/props DROPPED-SILENT). After: at
scene export, a `TEX_SKY` node feeding the World Background bakes a
Nishita-or-Hosek-Wilkie sky (per `sky_type`) into a temporary equirectangular
image loaded through the existing `renderer.load_environment_map` HDRI path,
with an explicit warning listing the sockets/props the bake does not honor
(sun disc, altitude, ozone/aerosol/air density, ground albedo); the coverage
matrix shows `TEX_SKY` SUPPORTED-or-APPROXIMATED-with-warning, never silent.

---

## Context

Filed per the owner's 2026-09-07 08:30 gate-(b) decision
(`north-star-and-integration-gate-2026-09-07.md` §2(b), reaudit backlog row
5). pkg63 (World/HDRI parity, done) explicitly deferred this: "Do not
implement Sky Texture node conversion (Hosek-Wilkie / Nishita). Separate
package — needs its own research note." `setup_world`
(`blender_addon/__init__.py:5232-5339`) already owns the exact insertion
point — it resolves an `hdri_path` string and hands it to
`renderer.load_environment_map(hdri_path, strength, rx, ry, rz, tint, ...)`.
A baked sky is just another `hdri_path` (a temp file), so no new engine
plumbing is needed for the floor — only a Python-side sky evaluator and a
bake-to-image step, which is genuinely new physics and therefore requires
`cite-algorithm` (CLAUDE.md §6) before writing it.

---

## Evidence

- 2026-09-07: live Blender 5.2.0 probe — `ShaderNodeTexSky().inputs =
  ['Vector']`; `sky_type` enum = `{SINGLE_SCATTERING, MULTIPLE_SCATTERING,
  PREETHAM, HOSEK_WILKIE}` — four models, not just "Nishita/Hosek";
  `SINGLE_SCATTERING`/`MULTIPLE_SCATTERING` are Cycles' current
  Nishita-family names, the other two are legacy analytic models.
- Coverage matrix (`docs/blender_parity/coverage_matrix.json`,
  `feature == "TEX_SKY"`, 2026-09-07): all 14 rows DROPPED-SILENT —
  `input:Vector`, `prop:sky_type`, `prop:sun_direction`, `prop:sun_disc`,
  `prop:sun_size`, `prop:sun_intensity`, `prop:sun_elevation`,
  `prop:sun_rotation`, `prop:altitude`, `prop:air_density`,
  `prop:aerosol_density`, `prop:ozone_density`, `prop:turbidity`,
  `prop:ground_albedo`.

---

## Reference

- `blender_addon/__init__.py:5232-5339` (`setup_world`) — the
  `TEX_ENVIRONMENT`/`BACKGROUND`/`MAPPING` walk and the `hdri_path` →
  `renderer.load_environment_map` call this package extends.
- pkg63 spec (explicit non-goal / deferral):
  `.astroray_plan/packages/pkg63-world-hdri-parity.md`.
- External (not vendored in `external/cycles_light_tree`, cite in code per
  CLAUDE.md §6): `intern/cycles/kernel/svm/sky.h` (Nishita
  single/multiple-scattering LUT model, current Cycles default) and
  `intern/cycles/kernel/svm/sky_model.h` (Hosek-Wilkie 2012 closed-form,
  `HOSEK_WILKIE`/`PREETHAM` legacy modes). Hosek & Wilkie, ACM TOG 2012;
  Nishita et al., SIGGRAPH 1993. `cite-algorithm` must run first — no
  reference implementation is vendored today.
- `docs/blender_parity/coverage_matrix.json` / `report.md` — regenerate via
  the pkg229 reproduce block after landing.

---

## Prerequisites

- [x] pkg63 done — HDRI load path (`load_environment_map`) exists and is
      the target integration point.
- [x] pkg229 done — coverage matrix regenerable headlessly.
- [ ] `cite-algorithm` run for the chosen sky model (research note saved to
      `.astroray_plan/docs/` per CLAUDE.md §6) before implementation starts.
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `blender_addon/sky_bake.py` | Standalone (no bpy-only calls beyond image I/O) sky evaluator: given `sky_type` + the sun/atmosphere props, produces an equirectangular `float32` RGB array, matching the cited Nishita or Hosek-Wilkie formulation. Two-lane structure (one function per model family) — no speculative third model. |
| `tests/test_pkg256_sky_bake.py` | TDD gate: a `TEX_SKY` world bakes to a non-uniform equirect image (bright near the sun direction, darker toward the horizon opposite it), `sky_type` changes the output, the degradation warning names the dropped sockets verbatim, and the resulting temp file loads successfully through `renderer.load_environment_map`. |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | `setup_world`'s node walk (`~L5259-5260`) gains a `node.type == 'TEX_SKY'` branch: calls `sky_bake.bake_to_equirect(node)`, writes the result to a session temp file (`tempfile.gettempdir()`, cleaned up after `load_environment_map` returns — no persistent artifact), and sets `hdri_path` to it; `strength`/tint/rotation continue to come from the sibling `BACKGROUND`/`MAPPING` nodes exactly as today. One `_warn_shader_fallback('TEX_SKY', ...)` call naming the dropped sockets (sun disc, altitude, ozone/aerosol/air density, ground albedo, `Vector` custom mapping). |

### Key design decisions

1. **Bake to a static HDRI at export time, not a live analytic world
   lookup.** The task's floor target and `setup_world`'s existing
   `hdri_path`-based contract both point here: one bake per render/preview
   refresh reuses 100% of the existing environment-map loader (rotation,
   tint, `blender_convention` coordinate swap) with zero engine changes.
   The ceiling (analytic per-ray sky evaluation in the engine's world
   lookup, avoiding a fixed-resolution bake) is Phase 2 and needs its own
   `cite-algorithm` pass against the LUT/closed-form math, not attempted
   here.
2. **Model scope: `SINGLE_SCATTERING`/`MULTIPLE_SCATTERING` (current Cycles
   Nishita) is the floor's primary target — highest real-world usage
   (Blender's default `sky_type` since 2.83).** `PREETHAM`/`HOSEK_WILKIE`
   are lower-frequency legacy choices; if `cite-algorithm` research shows
   implementing all four in one pass is disproportionate effort, landing
   Nishita first with `PREETHAM`/`HOSEK_WILKIE` routed to the Nishita bake
   plus a warning ("legacy sky model X approximated with Nishita") is an
   acceptable narrower floor — record the actual choice made in Progress.
3. **Sun direction**: read the resolved `sun_direction` vector prop
   directly rather than re-deriving it from `sun_elevation`/`sun_rotation`
   — one source of truth.
4. **No persistent cache file** — CLAUDE.md §2: re-bake every `setup_world`
   call. Viewport re-bake cost, if it matters, is a follow-up performance
   package with its own measurement.

---

## Acceptance criteria

- [ ] `tests/test_pkg256_sky_bake.py` passes: non-uniform bake, `sky_type`
      changes output, warning text asserted verbatim, temp file loads via
      `load_environment_map`.
- [ ] Coverage matrix regenerated: `TEX_SKY`'s implemented props (at minimum
      `prop:sky_type`, `prop:sun_direction`, `prop:sun_intensity`, plus
      whichever atmosphere props the chosen model consumes) move
      DROPPED-SILENT → SUPPORTED/APPROXIMATED; every prop the bake does not
      consume stays DROPPED-SILENT in the matrix **but** is named in the
      runtime warning asserted by criterion 1 — no prop is both
      unclassified and unwarned.
- [ ] Headless Cycles A/B: a tiny (64×64, low-SPP) outdoor scene (ground
      plane + Sky-textured world) renders on Astroray and Cycles; visually
      inspected side by side for sun-position and horizon-gradient
      plausibility (no numeric parity claimed — a bake is not the same
      model Cycles evaluates per-ray) and archived alongside the test.
- [ ] `cite-algorithm` research note exists under `.astroray_plan/docs/`
      before the bake evaluator lands, cited in `sky_bake.py`'s header.
- [ ] Signature sweep: `load_environment_map`'s call sites unchanged in
      count/shape (new caller, same signature) — grepped.

---

## Non-goals

- Analytic per-ray sky evaluation in the engine's world lookup (the
  ceiling) — Phase 2, needs its own research/citation pass.
- Sun disc rendering (a visible sun disc/glare in the sky image) —
  explicitly named in the floor warning as dropped.
- `altitude`, `ozone_density`, `air_density`, `aerosol_density`,
  `ground_albedo` — named in the warning, not consumed by the floor bake.
- Motion/animation-aware re-bake optimization — re-bake is unconditional
  per Key design decision 4.
- Implementing all four `sky_type` values with full accuracy in one pass —
  decision 2 allows a narrower floor; record the actual scope landed.

---

## Progress

- [ ] 2026-09-07 — filed per owner gate-(b) decision.

---

## Lessons

*(Fill in after the package is done.)*
