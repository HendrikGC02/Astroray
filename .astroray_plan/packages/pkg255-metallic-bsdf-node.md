# pkg255 — Metallic BSDF node (`ShaderNodeBsdfMetallic`)

**Pillar:** 5
**Track:** A
**Status:** done — PR #744, 2026-09-08, 9/9 tests green CPU+GPU on RTX 5070 Ti
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

- [x] `tests/test_pkg255_metallic_f82.py` passes: F82-mode renders a
      non-grey, Edge-Tint-responsive conductor; Roughness monotone;
      CPU/GPU parity in-band; `PHYSICAL_CONDUCTOR`-mode node renders without
      exception and the degradation report contains the exact warning text
      asserted by the test. MEASURED: 9/9 passed (4 stub-Blender dispatch +
      5 real-renderer, including the 2-case GPU/CPU parametrized parity
      test) on the RTX 5070 Ti, main-checkout build_cuda .pyd (HEAD
      fe535b6a, canary green).
- [x] Coverage matrix regenerated: `BSDF_METALLIC` shows Base Color,
      Edge Tint, Anisotropy, Rotation, Thin Film Thickness, Thin Film IOR,
      `prop:fresnel_type` moved DROPPED-SILENT → SUPPORTED or APPROXIMATED
      (all credited, none silent); Normal, Tangent, Weight
      remain DROPPED-SILENT but are provably APPROXIMATED-with-warning at
      render time per criterion 1 — the same classification-vs-runtime-
      warning residual pkg229 already documents for `BSDF_HAIR_PRINCIPLED`.
      `prop:distribution` was ALSO picked up as APPROXIMATED by the scanner
      (better than the minimum bar above — the `getattr(node,
      'distribution', ...)` read is itself AST-visible). IOR/Extinction
      correctly remain DROPPED-SILENT (Phase-2 PHYSICAL_CONDUCTOR ceiling,
      never read). Verified via `git diff docs/blender_parity/*` — exactly
      8 rows changed, all `BSDF_METALLIC`, all DROPPED-SILENT→APPROXIMATED,
      nothing else touched (APPROXIMATED 50→58, DROPPED-SILENT 363→355,
      SUPPORTED unchanged 114).
- [x] Headless Cycles A/B: a tiny (64×64, 32spp) scene with an F82-mode
      Metallic sphere (default node params, Blender's default
      `fresnel_type=F82`) rendered on Astroray (CPU, staged OpenMP-off addon
      .pyd) and on Cycles (CPU) via `benchmarks/blender_parity/render_leg.py
      --category shader_node --feature BSDF_METALLIC --bl-idname
      ShaderNodeBsdfMetallic`; visually inspected side by side (not a
      numeric parity gate). Both show a grey-metallic sphere with a bright
      area-light specular highlight in the same position over the same
      checker backdrop; per-channel means are close (Cycles
      R=0.2153/G=0.2125/B=0.2353 vs Astroray R=0.2152/G=0.2185/B=0.2370)
      despite independent 32-spp MC streams with no denoising (Astroray
      visibly noisier, expected). Archived under
      `test_results/2026-09-08-pkg255/` (`f82_metallic_cycles.{npy,png}`,
      `f82_metallic_astroray.{npy,png}`,
      `f82_metallic_sidebyside_256.png`, plus the Edge-Tint-responsiveness
      pair `f82_edge_tint_neutral.png` / `f82_edge_tint_tinted.png` saved by
      the test itself).
- [x] Signature sweep: no new `Material` virtuals or engine-facing
      signatures added (addon-only change) — confirmed by diff: only
      `blender_addon/__init__.py`'s `BSDF_METALLIC` branch inside
      `_standalone_bsdf_spec` changed (no new function/method signatures),
      plus the two regenerated coverage-matrix docs and the new test file.

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

- [x] 2026-09-07 — filed per owner gate-(b) decision.
- [x] 2026-09-08 — implemented. `blender_addon/__init__.py`'s
      `_standalone_bsdf_spec` `BSDF_METALLIC` branch: dropped the dead
      `Color`-socket else-branch (reads `Base Color` directly); reads Edge
      Tint / Anisotropy / Rotation / Thin Film Thickness / Thin Film IOR;
      branches on `fresnel_type` (F82 maps onto native-principled conductor
      keys `specular_tint`/`anisotropic`/`anisotropic_rotation`/
      `thin_film_thickness`/`thin_film_ior`, zero new engine code;
      `PHYSICAL_CONDUCTOR` warns verbatim and falls back to F82 defaults);
      unconditional named warnings for Normal/Tangent/Weight/distribution.
      New spec dict carries `native_params` so it rides
      `_create_native_principled_material` (pkg178) exactly like a
      Principled node would.
      Wrote `tests/test_pkg255_metallic_f82.py` (9 tests: 4 stub-Blender
      addon-dispatch, 5 real-renderer including a 2-case GPU/CPU parity
      parametrization mirroring `test_pkg178_principled_gpu_cpu_parity.py`'s
      metallic_r0.3/r0.6 band [0.95, 1.05]).
      Regenerated `docs/blender_parity/coverage_matrix.json` +
      `docs/blender_parity/report.md` headlessly (Blender 5.2,
      `scripts/generate_blender_parity_matrix.py`, staged OpenMP-off addon
      `.pyd`) — clean 8-row diff, all `BSDF_METALLIC`, all
      DROPPED-SILENT→APPROXIMATED.
      Ran the headless Cycles-vs-Astroray A/B via
      `benchmarks/blender_parity/render_leg.py` (category=shader_node,
      feature=BSDF_METALLIC, 64x64, 32spp, CPU); archived images under
      `test_results/2026-09-08-pkg255/`.
      GPU gate: 9/9 green on RTX 5070 Ti (main-checkout build_cuda .pyd,
      HEAD fe535b6a, canary green, single-lock session shared with pkg237).
      No engine/C++/CUDA files touched; no new `Material` signatures.

---

## Lessons

- The AST coverage-matrix scanner credits a socket/prop as read whenever
  the addon code contains a matching `node.inputs.get(...)` /
  `getattr(node, '<name>', ...)` pattern in the dispatch function it scans
  — it isn't limited to a hand-maintained table. Referencing
  `getattr(node, 'distribution', ...)` even just to NAME it in a warning
  message was enough to get `prop:distribution` upgraded from
  DROPPED-SILENT to APPROXIMATED, better than the spec's stated minimum
  bar (which expected it to stay DROPPED-SILENT, matching the pkg229
  `BSDF_HAIR_PRINCIPLED` residual pattern).
- Before regenerating a coverage matrix and comparing to a prior audit
  doc's headline numbers, diff against the ACTUALLY COMMITTED
  `coverage_matrix.json`, not the doc's prose table — the committed file
  had already drifted from the `blender-coverage-reaudit-2026-09.md`
  doc's claimed 152/35/340 figures (committed baseline was 114/50/363
  before this change), unrelated to this package. Comparing against the
  doc instead of the file briefly looked like a large unexplained
  regression; `git diff` on the actual file showed a clean, fully
  attributable 8-row change.
