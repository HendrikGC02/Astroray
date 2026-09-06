# pkg241 — Cooperative render cancellation and viewport-response contract

**Pillar:** 5 (Blender/DCC viewport response)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** landed pkg52/81/191/192/196 viewport machinery and pkg147
OpenMP/GIL safeguards; coordinate real Blender tests with DONE pkg236's (#711)
isolated-profile contract. DONE pkg232 (#705) owns delegate subprocess cleanup only.

Coverage specs: [pkg52](pkg52-persistent-viewport-session.md),
[pkg81](pkg81-viewport-interactivity-parity.md),
[pkg191](pkg191-viewport-gpu-progressive-refinement.md),
[pkg192](pkg192-viewport-navigation-interactivity.md),
[pkg196](pkg196-viewport-reduced-res-navigation.md),
[pkg147](pkg147-addon-cpu-render-hang.md),
[pkg232](pkg232-delegate-timeout-process-tree.md),
[pkg236](pkg236-hermetic-blender-smoke.md).

## Evidence

Static call-path evidence only — NOT measured latency:

- `blender_addon/__init__.py:1210` — `if self.test_break(): return False`;
  the full render continues at `:1276` regardless of the break result.
- `module/blender_module.cpp:2220-2227` — the `std::function<void(float)>`
  progress callback discards the Python return value; `renderer.render(...)`
  at `:2227` has no cancellation channel.
- `include/raytracer.h:4183` — `if (progress) progress(float(++tilesCompleted)
  / totalTiles);` — progress is a void fire-and-forget after each tile.
- GPU dispatch `module/blender_module.cpp:2171` — no cancellation or progress
  argument.
- `blender_addon/exporter.py:611` — blocking `renderer.render(...)` from
  `render_viewport_frame` (`:541`), reached from `view_draw` (`:724`) and
  `view_update` (`:651`).

None of the above is a measured responsiveness number; Phase 0 must produce
those before any code is written.

## Goal

A cooperative render-cancellation and viewport-response contract: the viewport
must acknowledge a cancel/restart request promptly, stop producing stale
frames, and return to a consistent session state without mixed accumulation or
leaked resources. Ordinary completion must be unchanged.

## Scoped direction

Phase 0 (mandatory, before coding): measure, SEPARATELY, matched CPU and GPU
UI-event latency, render-update latency, and cancellation
acknowledgement/completion latency; pin exact numeric budgets plus the
workload/settings/measurement protocol. The detailed architect pass then picks
the safe session/GIL/Blender-API/CUDA-ownership design; this spec does NOT
prescribe background threads. Phase 1 implements the approved bounded
cancellation/restart/stale-result contract; Phase 2 verifies its native and
Blender lifecycle behavior. Reuse `benchmarks/viewport_parity/run.py` and the
existing viewport stage recorder; extend canonical harnesses rather than fork.

## Acceptance — all implementation gates UNRUN

- [ ] Phase 0 budgets pinned: p50/p95/p99 on an expensive scene for UI-event,
      render-update, and cancellation acknowledgement/completion, CPU and GPU,
      with the exact workload/settings/protocol recorded.
- [ ] F12 cancel, camera change, scene replacement, shutdown/restart, and
      partial-failure paths behave per the contract.
- [ ] No mixed accumulation across cancel/restart; no leaked
      sessions/threads/resources.
- [ ] Ordinary completion path unchanged (bit-compatible where applicable).
- [ ] Isolated Blender CPU and native GPU visual evidence saved and
      Astra-reviewed.
- [ ] Caller/binding/ABI review for any native signature change; fresh native
      build identity if touched; GPU lock; at most two isolated implementation
      worktrees; independent Claude sign-off.

## Risks

GIL/thread ownership; partial CUDA state at cancellation boundaries; Blender API
re-entrancy in `view_update`/`view_draw`.

## Non-goals

No transport-math changes; no forced GPU preemption guarantees; no silently
changing the requested backend.
