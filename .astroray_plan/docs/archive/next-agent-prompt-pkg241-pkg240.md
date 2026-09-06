# Next-agent prompt — responsive Blender milestone

Use `$astroray-architect-round` for an autonomous delivery round. The milestone
is **responsive camera/material edits, reliable cancellation, and faithful
mapped textures** in real Blender, with an interactive GPU viewport and a
trustworthy CPU fallback.

Read `AGENTS.md`, `CLAUDE.md`, `KNOWLEDGE.md`, then the live planning hierarchy:
`.astroray_plan/docs/STATUS.md`, `NEXT_STAGE_REPORT.md`, and `ROADMAP.md`.
Read `rebuild-handoff-2026-09-06.md`, `pkg240-ci-baseline-audit.md`, and the
pkg241/pkg240 specs. Use the project index, inspect current git/GitHub state,
PRs, worktrees and GPU lock, and avoid duplicate dispatch. Treat old reports as
historical; pkg230b, pkg232 and pkg236 are already landed.

Lead with architecture, acceptance gates, dependencies and risks, then execute.
Use two bounded implementation lanes after their architectural reviews:

1. **pkg241 is the main feature.** Complete the existing interactive measurement
   harness and record actual Blender camera/material events, render updates,
   presentation and cancellation acknowledgement/completion separately on CPU
   and GPU. The interactive driver is currently a stub; native stage averages
   are not UI or cancellation percentiles. Pin the workload and p50/p95/p99
   budgets from measurements before behavior changes. Then implement the safe
   session/GIL/Blender-API/CUDA cancellation and stale-result design. Verify
   orbit, settle/refine, material edit, F12 cancel, restart, scene replacement,
   shutdown and partial failures on a representative expensive scene. No mixed
   accumulation, stale frames, leaked sessions or silent backend fallback.
2. **pkg240 is the parallel throughput lane.** Build on the filed baseline;
   no optimization has landed yet. After detailed architecture, measure a
   controlled matched-revision trial of the canonical split test runner.
   Preserve collection/node IDs, effective markers, skip/xfail/xpass semantics,
   serial/GPU/unclassified isolation, required checks, docs-only behavior and
   branch/internal-PR/fork trust boundaries. Distinguish elapsed latency from
   overlapping job time and billable usage. Adopt only a demonstrated benefit.

Preserve pkg230b affine image/program mapping during edits and cancellation.
For the faithful-mapped-texture milestone, inspect OPEN pkg242 procedural
mapping (including the reproduced UV-less checker mismatch) and pkg245
normal/bump provenance. If these changes are needed, deliver
them through their own architectural decisions and scoped PRs; do not bury
them in pkg241 or pkg240. Check shared file ownership before parallel edits.

Use Astra for architecture, integration, physics/ABI judgment, actual visual
inspection and merge decisions. Use bounded Spark workers where callable;
Spark was verified through the local Codex CLI even though the prior session's
native subagent roster omitted it. Use `astroray-opencode-delegator` for cheaper
bounded work, resolving tiers from the canonical policy without hard-coded
provider model IDs. While Claude is unavailable, Terra or DeepSeek is authorized
for independent review. Do not block on retrying unavailable Claude.

Keep at most two implementation worktrees, verify each worker's actual directory,
and serialize CUDA-heavy builds/renders under the GPU lock. Use pkg236 isolated
Blender profiles for tests. Preserve user files and the live Blender session;
the CUDA addon was rebuilt and installed after the owner closed Blender. Check
the rebuild handoff for exact artifact identity. Rebuild
stale native sources, verify the actual imported module and arch, inspect every
changed signature's callers/bindings, and save representative raw renders and
qualitatively inspected visual comparisons.

Investigate failed tests/reference images instead of assuming either the code
or reference is correct. Existing pkg237 HDRI and pkg238 ULP failures remain
open; pkg249 owns the informational reference-smoke failure. Do not report them
as passing or lower thresholds merely for green results. Preserve spectral,
dispersion, infrared/band-aware and robust physical transport foundations.
Pillar 4 remains PAUSED.

I authorize autonomous implementation, documented verification, independent
review, commit, push, PR creation and merge when the scoped gates pass. Favor
rapid bounded delivery and make reversible risks explicit. File valuable
tangents separately. Keep live planning records current and finish with what
shipped, actual timings/gates, visual proof, remaining risks and the next
eligible package. Proceed without routine permission questions.
