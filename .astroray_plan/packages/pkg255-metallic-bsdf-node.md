# pkg255 — Metallic BSDF node (`ShaderNodeBsdfMetallic`)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg178, pkg229, pkg253

---

## Goal

Before: `ShaderNodeBsdfMetallic` is read for exactly two of its fourteen
sockets/props (Base Color via a dead defensive branch that the AST scanner
misreads as a version-compat guard, and Roughness) and lowered to a crude
`metallic=1.0` Principled fallback — bypassing the F82-tint conductor model
(Gulbrandsen 2014 / Kutz-Hoffman) Astroray already ships for the Principled
BSDF's own metallic lobe, CPU **and** GPU. After: the node's `F82` Fresnel
mode (Base Color, Edge Tint, Roughness, Anisotropy, Rotation, Thin Film
Thickness/IOR) routes through that existing conductor machinery with the
coverage matrix showing it SUPPORTED-or-APPROXIMATED-with-warning per gate
(b); `PHYSICAL_CONDUCTOR` mode (direct complex-IOR Fresnel from IOR/
Extinction) and Normal/Tangent/Weight/`distribution` are APPROXIMATED with an
explicit warning naming each, never silently dropped.

---

## Context

Filed per the owner's 2026-09-07 08:30 gate-(b) decision: Metallic BSDF must
be SUPPORTED or APPROXIMATED-with-warning for the Pillar-4 exit gate
(`north-star-and-integration-gate-2026-09-07.md` §2(b)). Reading the addon
before writing anything (CLAUDE.md §1) found the pkg253 blind-spot pattern
recurring in miniature: `_standalone_bsdf_spec`'s `BSDF_METALLIC` branch
(`blender_addon/__init__.py:4024-4031`) already reads Base Color and
Roughness and calls `_warn_shader_fallback`, but the scanner's
`_extract_if_else_guarded_reads` treats the node's defensive
`if node.inputs.get('Base Color') is not None: ... else: color =
get_color_input(node, 'Color', ...)` as a cross-version socket-rename guard
and excludes both names from credited coverage — live-Blender-5.2 probe
(2026-09-07, `ShaderNodeBsdfMetallic().inputs`) confirms `Color` has never
existed on this node; the `else` branch is dead code, not a real
compatibility fallback. More importantly, the current handler never reaches
`principled.cpp`'s `conductorNK`/`thinFilmConductorRGB`/GPU
`gpu_pr_conductorNK` — the exact F82-tint physics this node needs — because
it routes through the generic `{'kind': 'principled', params: {metallic:
1.0, roughness}}` fallback spec instead of the native-principled conductor
path pkg178/pkg253 already wired end-to-end.

---

## Reference

- Coverage matrix: `docs/blender_parity/coverage_matrix.json`, `feature ==
  "BSDF_METALLIC"` (14 rows; live 2026-09-07: Roughness APPROXIMATED, the
  other 13 — Base Color, Edge Tint, IOR, Extinction, Anisotropy, Rotation,
  Normal, Tangent, Weight, Thin Film Thickness, Thin Film IOR,
  `prop:distribution`, `prop:fresnel_type` — DROPPED-SILENT).
- Reaudit backlog row 6: `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md`.
- Existing conductor/F82 implementation (reuse, do not reinvent —
  CLAUDE.md §6): `plugins/materials/principled.cpp:373-419`
  (`conductorNK`, `precomputeConductorNK`, `thinFilmConductorRGB`,
  `thinFilmConductorSpectral` — Gulbrandsen, "Artist Friendly Metallic
  Fresnel", JCGT 2014; Kutz & Hoffman F82-tint; Belcour-Barla 2017 thin
  film) and its GPU mirror `include/astroray/gpu_materials.h:1525-1580`
  (`gpu_pr_conductorNK`, `gpu_pr_thinFilmConductorRGB`,
  `gpu_pr_thinFilmConductorSpectral`).
- External (ceiling only, not vendored): `intern/cycles/kernel/closure/
  bsdf_microfacet.h` `bsdf_microfacet_setup_fresnel_conductor` (complex-IOR
  Fresnel from IOR+Extinction) — cite in code per CLAUDE.md §6 if Phase 2
  is scheduled; not reproduced here.
- pkg253 spec (sibling, same node-audit lineage): `.astroray_plan/packages/pkg253-principled-advanced-inputs.md`.

---

## Prerequisites

- [x] pkg178 done — native conductor/F82 machinery exists CPU+GPU.
- [x] pkg253 done — the native-principled param-plumbing pattern
      (`_principled_native_params`, `put_float`/`put_vec`) to mirror.
- [x] pkg229 done — coverage matrix regenerable headlessly.
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg255_metallic_f82.py` | TDD gate: F82-mode Metallic BSDF renders a tinted-edge conductor (not flat grey), Edge Tint changes grazing-angle color, monotone in Roughness, CPU/GPU parity within the existing conductor mean-ratio band; a `PHYSICAL_CONDUCTOR`-mode node renders (falls back to F82 params) and emits the degradation warning asserted verbatim. |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | `_standalone_bsdf_spec`'s `BSDF_METALLIC` branch (`~L4024-4031`): drop the dead `Color`-socket else-branch (read `Base Color` directly — removes the scanner false-negative without touching the scanner, CLAUDE.md §3); read `Edge Tint`, `Anisotropy`, `Rotation`, `Thin Film Thickness`, `Thin Film IOR`; branch on `fresnel_type` — `F82` maps Base Color/Edge Tint/Roughness/Anisotropy/Rotation/Thin-Film onto the same native-principled param keys pkg253's `_principled_native_params` already emits for the Principled metallic lobe (`specular_tint`≈Edge Tint, `anisotropic`, `anisotropic_rotation`, `thin_film_thickness`, `thin_film_ior`), so it rides the existing conductor path with **zero new engine code**; `PHYSICAL_CONDUCTOR` calls `_warn_shader_fallback('BSDF_METALLIC', 'complex-IOR conductor Fresnel is approximated with the F82-tint model; IOR/Extinction spectra are not read')` and falls back to F82 defaults. One `_warn_shader_fallback` call each (message names the socket) for Normal, Tangent, Weight, `distribution` — dropped, not silently ignored. |
| `docs/blender_parity/coverage_matrix.json` | Regenerated after the fix (headless Blender 5.2, pkg229 reproduce block). |
| `docs/blender_parity/report.md` | Regenerated alongside the matrix. |

### Key design decisions

1. **Reuse the existing conductor closure; do not write a new one.**
   `principled.cpp`'s F82/Gulbrandsen machinery already implements exactly
   the physics `ShaderNodeBsdfMetallic`'s `F82` Fresnel mode specifies — the
   gap is addon plumbing, not engine math. This mirrors pkg253 decision 1
   (investigate before implementing) and keeps the change addon-only, no
   C++/CUDA touched, no register-pressure risk on the shade kernel.
2. **`PHYSICAL_CONDUCTOR` (complex IOR from spectra) is the genuine ceiling
   item**, not a plumbing gap — Astroray has no direct complex-IOR Fresnel
   evaluator anywhere in the engine (CPU or GPU); building one needs
   `cite-algorithm` against `bsdf_microfacet.h`'s conductor setup before any
   code is written (CLAUDE.md §6). Phase 1 approximates it with F82 defaults
   plus a named warning; Phase 2 is the real closure.
3. **Removing the dead `Color`-branch is a genuine simplification, not a
   scanner workaround.** The live-Blender probe confirms no shipped version
   of this node ever exposed a `Color` socket, so the defensive fallback was
   speculative (CLAUDE.md §2). Deleting it is preferred over patching
   `_extract_if_else_guarded_reads` (CLAUDE.md §3 — that scanner mechanism
   is correct elsewhere, e.g. pkg253's `_float_with_fallback`).
4. **`distribution` (Beckmann/GGX/Multi-GGX) is a model-selection prop, not
   a value plug** — same class as pkg253's non-goal for Principled's own
   `distribution`/`subsurface_method`. Astroray's conductor lobe implements
   one model; selecting between three is a future package if ever
   prioritized, not part of this floor.

---

## Acceptance criteria

- [ ] `tests/test_pkg255_metallic_f82.py` passes: F82-mode renders a
      non-grey, Edge-Tint-responsive conductor; Roughness monotone;
      CPU/GPU parity in-band; `PHYSICAL_CONDUCTOR`-mode node renders without
      exception and the degradation report contains the exact warning text
      asserted by the test.
- [ ] Coverage matrix regenerated: `BSDF_METALLIC` shows Base Color,
      Edge Tint, Anisotropy, Rotation, Thin Film Thickness, Thin Film IOR,
      `prop:fresnel_type` moved DROPPED-SILENT → SUPPORTED or APPROXIMATED
      (all credited, none silent); Normal, Tangent, Weight,
      `prop:distribution` remain DROPPED-SILENT but are provably
      APPROXIMATED-with-warning at render time per criterion 1 — the same
      classification-vs-runtime-warning residual pkg229 already documents
      for `BSDF_HAIR_PRINCIPLED`.
- [ ] Headless Cycles A/B: a tiny (64×64, low-SPP) scene with an F82-mode
      Metallic sphere renders on Astroray and on Cycles; visually inspected
      side by side (not a numeric parity gate — no reference conductor
      parametrization match is claimed) and archived alongside the test.
- [ ] Signature sweep: no new `Material` virtuals or engine-facing
      signatures added (addon-only change) — confirmed by diff.

---

## Non-goals

- `PHYSICAL_CONDUCTOR` complex-IOR Fresnel from IOR/Extinction spectra —
  Phase 2 ceiling; needs `cite-algorithm` first, no engine code exists to
  build on.
- Normal / Tangent (per-lobe custom normal/tangent) — no per-lobe
  normal/tangent input exists on the native material, per pkg253's
  identical finding for Principled's own Coat Normal/Tangent.
- `Weight` (generic per-closure mix weight) — same non-goal as pkg253;
  needs a weighted-mix wrapper, separate package.
- `prop:distribution` (Beckmann/GGX/Multi-GGX selection) — model-selection
  prop, not a socket fix; Astroray implements one conductor model.
- GPU wavefront closure-graph changes — none needed; Phase 1 reuses the
  existing native-principled conductor path unchanged.

---

## Progress

- [ ] 2026-09-07 — filed per owner gate-(b) decision.

---

## Lessons

*(Fill in after the package is done.)*
