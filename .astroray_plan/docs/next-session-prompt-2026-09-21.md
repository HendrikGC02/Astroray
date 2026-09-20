# Next-session prompt — 2026-09-21 handoff

Paste everything below the line into a fresh Claude Code session opened in the main checkout. Written by
the outgoing lead (2026-09-19 23:00 → 2026-09-20 midday AEST; two usage-limit kills, every lane resumed by
raw agentId). Owner decisions it cites are in `north-star-and-integration-gate-2026-09-07.md` §7 and STATUS.md.

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside Blender 5.2.
Continue feature development and repo improvement autonomously, in **batched lanes** (owner 2026-09-11):
several independent items per worktree / build / sweep / CI cycle, one PR per batch with per-item sections
and tests.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` (north star, gate (a)–(f), §7).
3. `.astroray_plan/docs/STATUS.md` top block (2026-09-20 CURRENT).
4. The run report `.astroray_plan/docs/reports/2026-09-20-lead-session.html`.
5. Memory: `no-fable-agents`, `opus-4-8-not-opus-5-for-agents`, `agent-model-alias-opus-means-opus-5`,
   `lead-runs-builds-lanes-never-poll`, `continuing-agents-without-sendmessage`,
   `viewport-edit-verification-needs-pre-edit-frame` (new), `verify-attribution-with-a-baseline-build`,
   `ci_has_no_gpu_runtime_blindspot`, `delegate-tier-stalls-on-hard-packages` (2026-09-20 update),
   `deepseek-v41-flash-4x-grunt`, `concise-writing-style`.
6. Open specs: **pkg277** (coordinate-side op-VM warp, #822), **pkg272** (volume motion blur / multiscatter,
   optional), **pkg273** (cloud volume material — PAUSED horizon item), pkg265 Phase 3
   (`pkg265-phase3-gpu-walk-WIP-STATE.md`, worktree `Astroray-batchH`).

## State you inherit (verified 2026-09-20 midday)

- Main **9f586d75** + docs. Eight PRs merged this session: #836 #850 #843 #844 #839 #837 #838 #863. No open PRs.
- `build_cuda` rebuilt at 0888f278 (`.pyd` 13:14; #863 is tests-only so it is still current). Addon restaged
  and **installed**: build id `9f586d7+20260920T051940Z`, headless enable OK (`cie_cmf_1931_2deg`,
  `nishita_sky`, `set_volume_grid`, `set_object_holdout`, `last_render_info`, `soft_falloff`).
- **Final RTX sweep: 899 passed / 0 failed / 8 skipped / 9 xfailed / 1 xpassed, 6:30.** GPU lock free.
- Worktrees: main + `Astroray-batchH` (pkg265 Phase 3 WIP, untouched since 2026-09-13).
- **Colour:** the engine now integrates with the **CIE 1931 2°** observer (#837). Anything that pinned a
  colour baseline before 2026-09-20 is suspect — attribute against a build, do not re-baseline blind.

## Recommended dispatch order

Batch U — **light transport correctness** (the session's biggest open leads, all with measurements already
  on the issues): **#859** GPU loses the sun when a mesh emitter is present (sun-lit ground 0.22 → 0.027,
  CPU unchanged — a light-selection bug in the GPU power-CDF path); **#851** CPU light tree is 8–14× noisier
  than the power sampler (importance distance clamp vs Cycles `kernel/light/tree.h`) — this owns #763;
  **#852** area light with spread < 180° renders ~6× dark.
Batch V — **viewport** (owner-facing): **#849** in-place material / light / transform updates (the ~130 ms
  per-edit full re-sync from #850 is the floor); then #854 orbit tick gap, #855 storm re-measure, #857 render
  border on the worker path, #856 navigation-sample A/B. Do a real-navigation owner try-out (#858 has the
  checklist) before proposing any default flip.
Batch W — **volumes**: **#860** mesh-bounded volumes render 0.75–0.81 of Cycles while grid volumes match
  within 2 % (suspects: #833 AABB lowering, Volume Scatter/Absorption socket lowering, no equiangular
  sampling); **#833** mesh volume shape (the owner's icosphere-as-cube); **#842** only the nearest medium
  per ray segment.
Batch X — **parity fill**: **#862** CPU↔GPU red divergence (per-material furnace on the seven materials of
  `session_n1_envmap_cornell`; the gate now bounds the absolute gap), #767 residual on saturated colours,
  #773, #789/#783, #848 hero-λ refit, #845 orthographic cameras, #832 half-texel env lookup.
Batch Y — **shader coverage**: pkg277 (#822), #823 scanner + corpus proof cards, #846 scalar-program
  procedural inputs, #847 rotated-object Generated coordinates.
Then: pkg265 Phase 3 GPU walk (multi-build lane from the WIP STATE doc).

**Owner ask still outstanding:** one or two *pretty* Blender showcase scenes by a visually capable agent —
glass dispersion + caustics, volumes, Nishita sky + sun, thin film + metals, plus one black-hole scene if the
GR path still renders. Not started this session. The volumes showcase
(`test_results/batchQ/showcase_volumes_astroray_vs_cycles.png`) is the only new hero image.

## Method that worked (keep it)

- Lead runs **every** CUDA build in the background and resumes the lane when the `.pyd` is ready; lanes never
  poll and never edit `src/`, `include/`, `module/`, `CMakeLists.txt` between a BUILD REQUEST and the result.
- Every lane diff gets a `deepseek-v4.1-flash` critic pass with the diff inlined (US$0.003–0.007 each); the
  Opus reviewers (`cpp-abi-guard`, `cycles-parity-reviewer`) run per PR through a Workflow; `deepseek-v4-pro`
  applies the agreed fixes and the lead verifies and pushes. Total opencode spend this session: **US$0.049**.
- **CI has no GPU.** The closeout sweep is the first place GPU-marked gates run — budget one fix cycle for it
  (this session: 6 failures, all from the observer change, all fixed as metrics rather than by touching the engine).
- When a colour/physics change moves a pinned gate, build a **one-variable A/B** (revert only the data file on
  current main) before re-baselining. That is what settled #862.
