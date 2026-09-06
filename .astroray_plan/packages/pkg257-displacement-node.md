# pkg257 — Displacement (`ShaderNodeDisplacement` + material displacement method)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 3 sessions (~9 h)
**Depends on:** pkg223b, pkg229

---

## Goal

Before: the Material Output node's `Displacement` socket is never read
anywhere in the addon (`convert_node_material` reads only `Surface` and
`Volume`) — a `ShaderNodeDisplacement` node wired into it, and
`material.displacement_method`, are both silently ignored regardless of
value (all 5 sockets/props DROPPED-SILENT). After: `Displacement.Height`
(offset by `Midlevel`, magnitude from `Scale`) is approximated as a bump
perturbation through the existing pkg223b bump machinery — the same
`bump_map_texture`/`bump_strength`/`bump_distance` material params a
`ShaderNodeBump` on a BSDF's `Normal` already produces, now also reachable
from the Material Output's `Displacement` socket — with an explicit warning
when `displacement_method` requests true geometric displacement (`BOTH` or
`DISPLACEMENT`) or when `Normal`/`space` are wired, since neither is honored
by a bump-only approximation.

---

## Context

Filed per the owner's 2026-09-07 08:30 gate-(b) decision
(`north-star-and-integration-gate-2026-09-07.md` §2(b), reaudit backlog row
9, which explicitly scores this "S if bump-approximated"). pkg223b (done,
2026-08-29) already built and hardware-verified the CPU+GPU bump-perturbation
machinery this floor reuses — confirmed by reading
`blender_addon/__init__.py:2911-2948` (`get_normal_inputs`, which walks a
BSDF's `Normal` socket for a `ShaderNodeBump` and emits `bump_image`/
`bump_strength`/`bump_distance`) and `plugins/materials/normal_mapped.cpp`
(`NormalMappedPlugin`'s bump fields, CPU-verified) plus the GPU mirror
pkg223b added. The gap this package closes is different: Blender's
**Displacement** node lives on the *Material Output*'s `Displacement` input
(a separate socket from any BSDF's `Normal`) and reads `Height`, not a
`ShaderNodeBump`'s own inputs — that dispatch path does not exist at all
today, confirmed by a zero-hit grep for `"displacement"` across
`blender_addon/`.

---

## Evidence

- 2026-09-07: zero references to `ShaderNodeDisplacement`, `"Displacement"`,
  or `displacement_method` anywhere in `blender_addon/__init__.py`,
  `exporter.py`, or `settings_map.py`.
- 2026-09-07: live Blender 5.2.0 probe — `ShaderNodeDisplacement().inputs =
  ['Height', 'Midlevel', 'Scale', 'Normal']`; `space` enum =
  `{OBJECT, WORLD}`; `material.displacement_method` enum =
  `{BUMP, DISPLACEMENT, BOTH}` (Blender's own default is `BUMP` — i.e. even
  stock Cycles bump-approximates by default; `DISPLACEMENT`/`BOTH` opt into
  true geometry offset).
- Coverage matrix (`docs/blender_parity/coverage_matrix.json`,
  `feature == "DISPLACEMENT"`, 2026-09-07): all 5 rows DROPPED-SILENT —
  `input:Height`, `input:Midlevel`, `input:Scale`, `input:Normal`,
  `prop:space`.

---

## Reference

- pkg223b spec (bump machinery this reuses):
  `.astroray_plan/packages/pkg223b-bump-node.md`.
- `blender_addon/__init__.py:2911-2948` (`get_normal_inputs`) and
  `:4358-4369`/`:4145-4149` (bump params reaching
  `_create_material_from_shader_spec`) — the pattern this package extends
  to a second entry point (Material Output `Displacement`, not BSDF
  `Normal`).
- `blender_addon/__init__.py:2267-2284` (`convert_node_material`'s
  `Surface`/`Volume` read) — the function this package adds a
  `Displacement` read to.
- External (cited already in pkg223b, reused unchanged): Cycles
  `intern/cycles/kernel/svm/displace.h` (`svm_node_set_bump`),
  Mikkelsen 2010 surface-gradient bump.

---

## Prerequisites

- [x] pkg223b done — CPU+GPU bump perturbation hardware-verified.
- [x] pkg229 done — coverage matrix regenerable headlessly.
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg257_displacement_bump.py` | TDD gate: a Material Output with a `ShaderNodeDisplacement` wired into `Displacement` (Height fed by an image or procedural texture) renders visible bump relief identical in mechanism to an equivalent `ShaderNodeBump`-on-Normal scene (reuses pkg223b's own render assertions); `Midlevel`/`Scale` change relief direction/magnitude monotonically; `displacement_method in (DISPLACEMENT, BOTH)` and a linked `Normal` input each emit the degradation warning asserted verbatim; geometry vertex count is unchanged (proves no true displacement occurred, which the warning must be honest about). |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | `convert_node_material` (`~L2261-2284`): also read `output.inputs.get('Displacement')`; if linked to a `DISPLACEMENT`-type node, extract `Height` (via `get_image_from_socket`, mirroring `get_normal_inputs`'s `BUMP` branch), `Midlevel`/`Scale` (via `get_float_input`), and pass them into `convert_shader_node` (new optional parameter) so the returned spec gains `bump_map_texture`/`bump_strength` (from `Scale`)/`bump_distance` before `_create_material_from_shader_spec` runs — reusing the plumbing keys its `~L4145-4149` loop already forwards, no change needed there. `Midlevel` shifts the sampled height (`height - midlevel`), matching `svm_node_set_bump` centering. `_warn_shader_fallback('DISPLACEMENT', ...)` names `Normal` (dropped) and, when `displacement_method != 'BUMP'`, that true geometric displacement was requested but bump-approximated. |
| `docs/blender_parity/coverage_matrix.json` | Regenerated after the fix (headless Blender 5.2, pkg229 reproduce block). |
| `docs/blender_parity/report.md` | Regenerated alongside the matrix. |

### Key design decisions

1. **Displacement's `Height` becomes a bump texture, not a new closure.**
   pkg223b already proved the CPU+GPU surface-gradient bump math at
   parity; this package's entire job is a second addon-side entry point
   (Material Output `Displacement` in addition to BSDF `Normal`) feeding
   the same material params. Zero engine (C++/CUDA) changes.
2. **`convert_shader_node` gains one optional parameter** (the extracted
   displacement bump params) rather than a second global/thread-local
   channel — keeps the data flow explicit and traceable (CLAUDE.md §2:
   minimum change, no hidden state).
3. **Honesty about the ceiling.** Blender's own default `displacement_method`
   is `BUMP`, so this floor matches Cycles' *default* behavior exactly for
   the common case; the warning fires only when the scene explicitly opted
   into `DISPLACEMENT`/`BOTH` or wired a custom `Normal` — default-method
   scenes get zero spurious warnings.
4. **`space` (`OBJECT`/`WORLD`)** only matters for true displacement
   direction; folded into the same `displacement_method != BUMP` warning
   (one consolidated message, not a warning storm per socket).

---

## Acceptance criteria

- [ ] `tests/test_pkg257_displacement_bump.py` passes: relief visible,
      Midlevel/Scale monotone, warnings asserted verbatim for
      `Normal`-linked and non-`BUMP` `displacement_method` cases, vertex
      count unchanged (proves floor scope honestly).
- [ ] Coverage matrix regenerated: `input:Height`, `input:Midlevel`,
      `input:Scale` move DROPPED-SILENT → APPROXIMATED; `input:Normal` and
      `prop:space` remain DROPPED-SILENT in the matrix **but** are named in
      the runtime warning asserted by criterion 1 — no prop is both
      unclassified and unwarned.
- [ ] Headless Cycles A/B: a tiny (64×64, low-SPP) scene with a tessellated
      plane, an image-textured Height driving Displacement, renders on
      Astroray (bump-approximated) and Cycles (`BUMP` method, so the
      comparison is apples-to-apples) side by side; visually inspected for
      relief-direction plausibility (no numeric parity gate — different
      derivative sources per pkg223b's own documented CPU/GPU parity band)
      and archived alongside the test.
- [ ] Signature sweep: `convert_shader_node`'s new optional parameter —
      grep every call site (production + `tests/`) and confirm each passes
      the argument or relies on its default unchanged.

---

## Non-goals

- True geometric displacement (mesh subdivision/offset at export, or
  engine-side micro-displacement) — the ceiling; needs Blender's own
  displacement-to-mesh bake or engine subdivision infrastructure that does
  not exist today. Separate package.
- `Normal` input (custom analytic normal feeding the displacement gradient)
  — the bump path derives its own gradient from `Height`; named in the
  warning, not consumed.
- `space` (`OBJECT`/`WORLD`) — folded into the same warning as decision 4.
- Volume displacement / `PRINCIPLED_VOLUME` Displacement chains — unrelated
  code path.
- Any change to `plugins/materials/normal_mapped.cpp` or GPU bump kernels —
  pkg223b's machinery is reused unchanged.

---

## Progress

- [ ] 2026-09-07 — filed per owner gate-(b) decision.

---

## Lessons

*(Fill in after the package is done.)*
