# pkg201 Stage 1 — addon-side settings-honour: results & delta

**Run:** 2026-08-14, RTX 5070 Ti. Driver: `scripts/verify_pkg200_honour_matrix_run.py`
(the pkg200 driver, corrected in-place by pkg201 — see below), re-run VERBATIM on
my addon build via `--addon-dir dist/astroray`.
**Engine `.pyd`:** `dist/astroray/astroray.cp313-win_amd64.pyd`, mtime
2026-08-14 19:40:55 (OpenMP-OFF, sm_120 via cuobjdump `--list-elf`; built with
`dev_addon.ps1 -Smoke`, register + liveness smoke PASS on Blender 5.1 AND 5.2).
My change is Python-only (addon), so this engine binary == current main.
**Method:** identical to pkg200 — per-row A/B through the TRUE F12 path
(`bpy.ops.render.render`, CUSTOM_RAYTRACER, GPU), 32-bit LINEAR EXRs
(`apply_gamma=False`), per-channel mean/max/variance via cv2 (never SSIM),
pinned nonzero seeds, `PKG200_LEG PASS` sentinel-gated. Results byte-identical on
5.1 and 5.2 unless noted.

## Closed rows (before pkg201 -> after pkg201)

| Stage | Row | pkg200 verdict (#616) | pkg201 verdict | Measured (LINEAR, this run) |
|-------|-----|-----------------------|----------------|-----------------------------|
| 1 | world_max_bounces | **HONEST-FAIL** (1.0971 = 1.0971) | **PASS** | lum_mean A(0)=0.20931 -> B(12)=1.0969, ratio 5.241 (5.1 ≡ 5.2) |
| 1 | use_light_tree | **KNOWN-GAP** (inert; no pixel change) | **NEEDS-VISUAL — confirmed honoured** | \|dLum\| mean 0.02809 (5.1) / 0.03713 (5.2); both frames valid lit renders differing only in the NEE sampler noise field (multimodal Read) |

### world_max_bounces (Finding B)
The addon read `world.light_settings.max_bounces` — the ambient-occlusion
datablock, which has **no** `max_bounces` member — so `getattr(..., 1024)` always
won and the control was inert. Fixed to `world.cycles.max_bounces` (the real
Cycles world light-path prop; the GPU wavefront already gates env contribution on
`bounce <= worldMaxBounces`, `stage_advance.cu:312`). The pkg200 driver Row
encoded the bug as its override path (`world.light_settings.max_bounces`), which
`_apply_overrides` silently skips as a non-existent attr — so the row could never
flip on a verbatim re-run. Closing Finding B therefore includes repointing that
Row (and the `check_completeness` alias) to `world.cycles.max_bounces` so the
matrix tests the corrected attribute.

### use_light_tree (promoted from KNOWN_GAPS)
The addon read the custom UI tri-state directly and passed it to
`set_light_sampler`, which **threw** for `'uniform'`/`'light_tree'` (engine
accepts only `'power'`/`'tree'`, `blender_module.cpp:1531`) — a latent crash only
masked because the default is `'power'`. pkg201 `resolve_light_sampler` reconciles
the native `use_light_tree` bool AND translates the UI enum to a valid engine
token: True->`'tree'`, False->`'power'` (the engine has no uniform sampler, so
uniform collapses to power — stays APPROXIMATED). A new `use_light_tree` MATRIX
row + `many_lights` scene were added (KNOWN_GAPS now empty). The scene uses pure
**Emission-shader** spheres — the addon maps those to the hittable
`create_material('light',...)` NEE emitter (`__init__.py:3657`); a Principled-BSDF
emission is not an NEE light and leaves the tree empty (the near-black
false-negative first hit during bring-up). Toggling the native prop now changes
the GPU wavefront render measurably; visual confirm: both A(power)/B(tree) are
valid lit rooms differing only in sampler noise (not garbage).

## Control spot-check (untouched rows — driver edits must be benign)

| Row | pkg201 verdict | Measured | Matches #616? |
|-----|----------------|----------|---------------|
| film_exposure | PASS | per-ch mean-ratio 2.000, 2.000, 2.000 | yes (2.000) |
| max_bounces | PASS | lum_mean 0.034429 -> 0.43035, ratio 12.500 | yes (12.5×) |
| seed_repeat | PASS | \|dLum\| max ≤ 7.9e-07 (reproducible) | yes |

The in-place driver corrections (world_max_bounces override repoint,
`light_sampling` promoted to `_PLUMBED_APPROXIMATED`, new `use_light_tree` row,
`_alias` additions, empty `KNOWN_GAPS`) leave every neighbouring row's verdict
and numbers unchanged. `check_completeness()`: 26 plumbed props -> 26 rows, OK.

## Not in scope / follow-ups
- Stage 2 (Findings D/E/F) and Stage 3 (Findings A/C) remain open per the spec.
- The engine has no dedicated **uniform** light sampler; the UI `uniform` enum
  value collapses to `'power'` at the engine boundary (a pre-existing condition
  surfaced, not introduced, by pkg201). If a real uniform sampler is wanted that
  is a separate engine package.
