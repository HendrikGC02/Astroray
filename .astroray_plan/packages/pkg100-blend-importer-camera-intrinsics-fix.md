# pkg100 — .blend importer camera-intrinsics dynamic-attr defect

**Pillar:** 5 (addon / importer tooling)
**Track:** A (core quality / correctness — small, well-localized C++/Python fix; not a hardware-gated package)
**Codex-paste-ready:** yes — defect is fully localized to three named files with exact line citations, the fix is a one-of-N small change with no algorithm research required (CLAUDE.md §6 N/A: this is plumbing, not a physics/numerical algorithm), and the acceptance test is mechanically specified. The only judgement call is the fix-axis choice, which the spec lays out explicitly.
**Status:** done (PR #339 + #341, 2026-05-22 — Axis 2 fix: return intrinsics up call chain; `_blend_import_stats` stashed best-effort + bpy-free regression test added)
**Depends on:** none
**Estimated effort:** small (well under a day; the change itself is a few lines, most of the time is the real-Renderer regression test)

---

## Goal

**Before:** Every `.blend` import via `tools/blend_import/blend_to_astroray.py::import_blend`
fails at camera-emit time with:

```
AttributeError: 'astroray.Renderer' object has no attribute '_cam_intrinsics'
and no __dict__ for setting new attributes
```

…against the **real** pybind11 `astroray.Renderer`. The importer never
reaches rendering. The deferred pkg76 §3.5 parity-CSV follow-up
(Classroom / Junkshop / BMW27 RTX parity rows in `NEXT_STAGE_REPORT.md`)
is blocked behind this — no honest SSIM data can be produced because the
import dies before any pixels are rendered.

**After:** A `.blend` imported through the actual pybind11
`astroray.Renderer` carries its camera intrinsics through to
`setup_camera` without `AttributeError`. A regression test exercises the
real binding (not a Python stub) and the pkg76 §3.5 parity run can
proceed past camera emit.

---

## The defect (verified 2026-05-17 on HEAD `321464f`)

1. `tools/blend_import/scene_builder.py:175` — `_emit_camera` executes:

   ```python
   ctx.renderer._cam_intrinsics = {
       "eye": eye, "target": target, "up": up,
       "fov": vfov_deg, "aspect": aspect,
       "near": clipsta, "far": clipend,
   }
   ```

   It stashes the decoded camera intrinsics as a **dynamic Python
   attribute** on the renderer object.

2. `tools/blend_import/blend_to_astroray.py:60` — `import_blend` later
   reads them back with `getattr(renderer, "_cam_intrinsics", None)` and
   calls `setup_camera` if `width`/`height` were supplied. (Line 68 does
   the same with `renderer._blend_import_stats = stats` — **this is a
   second instance of the same defect on the same object** and must be
   fixed by the same change; do not fix line 175 alone.)

3. `module/blender_module.cpp:1595` declares:

   ```cpp
   py::class_<PyRenderer>(m, "Renderer")
   ```

   **without `py::dynamic_attr()`**. `grep dynamic_attr module/blender_module.cpp`
   → no matches. pybind11's default class has no `__dict__`, so any
   attribute assignment not backed by a registered `def_readwrite` /
   property raises `AttributeError`.

**Effect:** the assignment at `scene_builder.py:175` raises immediately;
every `.blend` import fails before rendering. Confirmed reproducing on
both the pkg76-csv worktree and main HEAD. The last commit to touch
`tools/blend_import/` is the merge that introduced the importer:
`59028079` — `feat(pkg76): Astroray .blend importer (parity scope) (#240)`,
2026-05-10. No commit since touches that directory.

**Why existing tests missed it:** `tests/test_blend_import_roundtrip.py:24`
defines a `_FakeRenderer` plain Python class. A plain Python class has a
`__dict__`, so `renderer._cam_intrinsics = {...}` succeeds against the
stub and the round-trip test passes — while the real pybind11
`astroray.Renderer` (no `__dict__`) fails. The test substitutes a stub
with the opposite attribute behaviour from the production object, so the
defect was structurally invisible to the suite. The regression test in
this package must close that gap by exercising the real binding.

---

## Reference

### Internal

- [`tools/blend_import/scene_builder.py`](../../tools/blend_import/scene_builder.py) — `_emit_camera`, line 175 (the failing assignment).
- [`tools/blend_import/blend_to_astroray.py`](../../tools/blend_import/blend_to_astroray.py) — `import_blend`, lines 60 (read-back) and 68 (`_blend_import_stats`, second instance of the same pattern).
- [`module/blender_module.cpp`](../../module/blender_module.cpp) — line 1595, the `py::class_<PyRenderer>(m, "Renderer")` binding.
- [`tests/test_blend_import_roundtrip.py`](../../tests/test_blend_import_roundtrip.py) — `_FakeRenderer` (line 24); the stub that masked the defect.
- [`.astroray_plan/packages/pkg76-blend-importer-parity-scope.md`](pkg76-blend-importer-parity-scope.md) — the parent package this unblocks.

### External

None. This is a pybind11 object-model plumbing defect, not a
physics/sampling/numerical algorithm (CLAUDE.md §6 does not apply). The
only external reference worth noting is the pybind11 documentation on
`py::dynamic_attr()` (object class customization) — read for
understanding the ABI/footgun tradeoff below; no code is mirrored.

---

## Fix — tradeoff axes (implementer/owner chooses)

This is a genuine fork with no single dominant answer. The axes are laid
out honestly per the CLAUDE.md Design rule; the spec does **not** force a
ranked N-option menu, and does not pre-pick a winner because the right
choice depends on how much the owner wants to constrain the renderer's
public attribute surface.

**Axis 1 — `py::dynamic_attr()` on the `Renderer` binding.**
Add `py::dynamic_attr()` to the `py::class_<PyRenderer>(m, "Renderer")`
declaration at `blender_module.cpp:1595`. Smallest possible diff (one
token), zero Python changes, both the `_cam_intrinsics` and
`_blend_import_stats` instances fixed at once.
- *Cost:* widens the class's attribute surface — any typo'd attribute
  assignment anywhere now silently succeeds instead of raising, and the
  object grows a per-instance `__dict__` (small per-object memory + a
  pybind11 ABI surface change on the type object). This is a binding-ABI
  change to a core type and **must go through cpp-abi-guard review**
  (memory: the project treats pybind11 type-object changes as ABI). It
  also legitimizes "stash arbitrary state on the renderer" as a pattern,
  which is the anti-pattern that produced this defect.

**Axis 2 — return intrinsics up the call chain instead of stashing.**
Have `_emit_camera` / `build_scene` *return* the camera intrinsics (a
small frozen dataclass or a typed tuple) and have `import_blend` thread
that return value to `setup_camera`, removing the
`renderer._cam_intrinsics` write entirely. Do the equivalent for
`_blend_import_stats` (return it from `build_scene` — it already returns
`stats`; only the `renderer._blend_import_stats = stats` line at
`blend_to_astroray.py:68` needs rerouting to the function return).
- *Cost:* no C++ change, no ABI risk, and it removes the root-cause
  pattern rather than enabling it. Touches the importer call chain
  (`build_scene` signature → `_emit_camera` → `import_blend`) and any
  caller that reads `renderer._cam_intrinsics` / `_blend_import_stats`
  off the returned renderer. **Sweep required:** grep the repo (incl.
  the pkg71 harness, `scripts/`, and tests) for `_cam_intrinsics` and
  `_blend_import_stats` before changing the contract; `blend_to_astroray.py`
  docstring (lines 43–51) advertises `_cam_intrinsics` as the public
  carrier and must be updated. Slightly larger diff, but localized to
  Python the implementer owns.

**Axis 3 — thin Python wrapper around `astroray.Renderer`.**
Wrap the real renderer in a small Python class (which has a `__dict__`)
that delegates the C++ methods and holds the importer's scratch
attributes. No C++ change.
- *Cost:* an extra indirection layer for the whole importer path, a
  delegation surface to maintain as the C++ `Renderer` API grows, and it
  preserves the "stash on the renderer" pattern (just on a proxy). Most
  code for the least conceptual cleanup; generally the weakest of the
  three unless an external caller specifically needs a renderer object
  that carries these attributes.

**Architect note (not a mandate):** Axis 2 is the only option that
removes the root-cause pattern with zero ABI risk and is the most
defensible long-term; Axis 1 is the right call **only if** the owner
explicitly wants a renderer that accepts ad-hoc Python attributes (and
accepts the cpp-abi-guard review + the silent-typo footgun). The
implementer should pick Axis 2 unless the owner states otherwise, but
the choice is genuinely theirs — do not treat this note as a hard
requirement.

---

## Acceptance criteria

- [ ] A regression test imports a real `.blend` through the **actual
      pybind11 `astroray.Renderer`** (constructed via `astroray.Renderer()`
      or by letting `import_blend` construct it — *not* a Python
      stub/`_FakeRenderer`) with `width`/`height` supplied, and asserts
      the camera intrinsics flow through to `setup_camera` without
      `AttributeError`. The test must fail on current HEAD (pre-fix) and
      pass after the fix. It should be skipped cleanly (not errored) when
      the compiled `astroray` module is unavailable, so CI without a
      built `.pyd` stays green, but it must NOT be satisfiable by a stub.
- [ ] The `_blend_import_stats` assignment at `blend_to_astroray.py:68`
      is covered by the same fix (not left as a latent second failure).
- [ ] Whichever axis is chosen, `tools/blend_import/blend_to_astroray.py`
      docstring (lines ~43–51, which advertise `_cam_intrinsics` as the
      public carrier) is updated to match the new contract.
- [ ] Repo-wide call-site sweep for `_cam_intrinsics` and
      `_blend_import_stats` performed and reported in the PR (per
      CLAUDE.md "Before you push"), including tests, the pkg71 harness,
      and `scripts/`.
- [ ] If Axis 1 is chosen: the PR explicitly flags the pybind11
      type-object ABI change for cpp-abi-guard review.
- [ ] pkg76 §3.5 parity run (`NEXT_STAGE_REPORT.md`) can proceed past
      camera emit — i.e. a Classroom/Junkshop/BMW27 import no longer dies
      at `_emit_camera`. (This package does **not** itself populate the
      parity CSV; it unblocks the deferred pkg76 CSV follow-up.)
- [ ] CI green on the new branch.

## Hard non-goals

- **No parity CSV population here.** This package only unblocks the
  pkg76 §3.5 follow-up; it does not produce SSIM rows.
- **No broader importer refactor.** Touch only what the chosen axis
  requires (CLAUDE.md §3 Surgical Changes). Do not "improve" adjacent
  importer code.
- **No fabricated parity data** anywhere, consistent with the honest
  `skip_reason` the orchestrator already recorded.

---

## Provenance

Discovered during the roadmap-orchestrator pkg76 dispatch tick on
2026-05-17. The dispatched implementer attempting the pkg76 §3.5 parity
CSV follow-up hit `AttributeError` at `scene_builder.py:175` against the
real `astroray.Renderer` and honestly recorded the blockage in a parity
CSV `skip_reason` column (no fabricated SSIM data). The orchestrator
verified the defect reproduces on both the pkg76-csv worktree and main
HEAD (`321464f`) and confirmed the root cause is the missing
`py::dynamic_attr()` on the `Renderer` pybind11 binding introduced by
merged PR #240 (`feat(pkg76): Astroray .blend importer (parity scope)`,
2026-05-10).
