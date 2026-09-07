# Next-session prompt — 2026-09-07 evening handoff

Paste everything below the line into a fresh Claude Code (Fable 5.1) session
opened in the main checkout. It is written by the outgoing lead session; the
owner's decisions it cites are recorded in
`north-star-and-integration-gate-2026-09-07.md` §7 and STATUS.md.

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven
from inside Blender 5.2. You are continuing feature development and repo
improvement in the same manner as the previous lead session (2026-09-07),
autonomously, for a long unattended stretch. The owner is not watching in real
time; work fast, break things behind tests, and leave a morning-readable record.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` — the
   owner-approved north star, the measurable Pillar-4 exit gate (a)–(f), the
   round sequencing, and §7 owner decisions (morning + evening).
3. `.astroray_plan/docs/STATUS.md` top two blocks (2026-09-07).
4. Specs for the lanes below: pkg258, pkg241, pkg237, pkg259, pkg253, pkg255,
   pkg242 (`.astroray_plan/packages/`), plus
   `hdri-background-gap-diagnosis-2026-09-07.md` and
   `pkg241-cancellation-design-2026-09-07.md`.
5. `python scripts/project_index.py whatis pkg258` etc. for dependencies;
   `scripts/README.md` before writing any script (§5b: no duplicate scripts).
6. Your memory directory (`~/.claude/projects/<this project>/memory/`); every
   entry there was earned the hard way.

## Hard constraints (owner directives — do not reinterpret)

- **Models.** Never spawn Fable subagents. High-reasoning subagents run on
  **Opus 4.8** (`claude-opus-4-8`), never Opus 5. Low-level/mid work on
  **Sonnet 5**. Bounded grunt work (docs flips, lint fixes, report assembly,
  well-specified small implementations) goes to open-weight models through
  `python .claude/skills/delegate/scripts/delegate.py --tier grunt --agent grunt
  --model opencode-go/glm-5.3-flash --dir <worktree> --prompt-file <f>`;
  pre-review critique through `--tier verify --agent critic --model
  opencode-go/glm-5.3`. Delegated output is evidence to verify, never trusted.
- **Codex** is a CLI second-opinion reviewer only: `codex exec -m gpt-5.6-terra
  -s read-only -c model_reasoning_effort='"high"' - < prompt.txt` at most
  **4 Terra calls** this session (design reviews of pkg258 estimator wiring and
  pkg241 Phase 2 are the two that matter); `gpt-5.6-luna` freely for sanity
  checks. **Astra (gpt-6-astra) only for the pkg259 Phase 0 creative
  brainstorm** — the owner asked for that collaboration explicitly; do not spend
  Astra on anything else and never let Codex orchestrate.
- **Blender.** Launch it yourself: `pwsh scripts/dev/launch_blender_mcp.ps1
  -Watch` (official `mcp` extension bridge on 9876; `check_blender_mcp.ps1` to
  diagnose). Blender 5.2 is installed locally; do headless renders yourself
  with `blender -b`, isolated profiles per pkg236.
- **GPU.** One CUDA build or GPU verifier at a time under
  `.astroray_plan/.orchestrator.gpu.lock` (`scripts/roadmap_orchestrator/locks.py`).
  Before quoting any GPU number: `.pyd` mtime vs `git log -1 --format=%cd
  HEAD`; rebuild if older (`scripts/build/build_cuda.bat`; if sccache drops
  the >10-min `stage_advance.cu` compile use the launcher-free variant —
  memory `sccache-drops-long-cuda-compiles`); confirm `astroray.__file__`
  is `build_cuda/astroray.cp313-win_amd64.pyd` and `cuobjdump --list-elf`
  shows sm_120. The `.pyd` is stale vs HEAD right now (08:45 build; only
  docs and addon Python landed after it) — rebuild before the first GPU gate.
- **Worktrees.** Every code-writing subagent gets its own `git worktree add`;
  its first action verifies `git rev-parse --show-toplevel`. Max 3 concurrent
  implementation worktrees. Remove a worktree only when its PR is MERGED and
  `git status --porcelain` is empty; delete the orphan directory too.
- **Merging.** Code: PR + CI green + local GPU gate → `gh pr merge --squash`
  (auto-merge is disabled on the repo). Pure `.astroray_plan/` docs may commit
  directly to main. Anything touching `scripts/`, `.github/`, `.claude/hooks`,
  `.claude/settings.json` goes through a PR merged before feature PRs.
  Before pushing: list every changed signature and grep the repo for call
  sites (tests, mocks, bindings included).
- **Specs.** TEMPLATE v2; `python scripts/project_index.py lint <spec>` must
  pass (pre-commit hook + CI `spec-lint`). File follow-ups of shipped work
  only; the spec-filing rate already exceeds implementation.
- **Git hygiene lessons from the last session:** commit WIP early (a usage
  limit killed three lanes at 02:10); never `git commit -a` while a
  cherry-pick is applied; never `Stop-Process` by command-line match (it
  killed the lead's own session for nine hours — use pid files, exclude
  `$PID`, match exe + script).
- **Keep `test_results/`** untouched except regenerable caches.
- **Design help:** present real tradeoff axes, no forced N-option ballots.

## State you inherit (verified 2026-09-07 ~21:30)

- main at the handoff commit, 0 open PRs, only the main worktree, CI green,
  spec lint clean (234 baselined legacy specs), index rebuilt.
- Viewport after pkg241 Phase 1a: GPU p95 edit→present metal_sweep camera
  32 ms / material 155 ms; 100k-tri camera 63.5 ms / material 224 ms.
  Gate (a) camera classes pass; material classes are render-bound.
- pkg238 done (#738). pkg237 open: owner chose a firefly-free parity scene
  for the 0.9628-vs-0.97 residual.
- pkg242 Phase 1 landed (#737 + fe1c95c); Phase 2 (real-Blender parity) open.
- pkg253: CPU alpha shadows landed (#728); GPU alpha is a strict xfail
  because the wavefront resolves occlusion in the deferred shadow stage.
- Addon: `dist/astroray-4.0.0-cuda.zip` is built and smoke-passed; the
  owner's live Blender profile runs the new exporter Python but the old
  native module. Install the zip only when Blender is closed.
- Weekly bench scheduled task `Astroray-WeeklyBench` (Sundays 03:00) runs
  locally and never commits; results land under `benchmarks/**/results`.
- Owner manual items still outstanding: paste
  `.astroray_plan/tracker/astroray_dashboard.gs` into Apps Script and run
  `refresh()`; add `spec-lint` to required checks; review the ghost GitHub
  app workflows. Mention them again in your morning message; do not do them.

## Dispatch order (the outgoing lead's choice; the owner delegated it)

Run lanes 1–3 in parallel worktrees; lane 4 needs no GPU and no worktree
beyond docs. Serialize every CUDA build.

1. **pkg258 — environment NEE + importance sampling (Opus 4.8 implementer;
   Terra review of the estimator wiring before the GPU leg).** The owner's
   top suspicion and a gate (c) blocker. Order inside the spec: research
   note via `cite-algorithm` → azimuth fix + sampler contract test on CPU and
   GPU (the test must be red on main first) → CPU NEE in the in-header tracer
   with the sun-disc convergence gate and a linear white furnace → CPU
   wavefront kernel + multiwavelength tracer → GPU wavefront (watch REG 254,
   use the `__noinline__` runtime-flag pattern if it spills) → re-run HDRI gap
   experiment 1a and re-derive `HDRI_MIN_BACKGROUND_MEAN` from the `.hdr`
   decode. Land it as at least two PRs (CPU, GPU). Save renders; inspect them.
2. **pkg241 Phase 1b, then Phase 2 measurement (Opus 4.8).** Phase 1b: the
   bool-returning cancellation callback with completion metadata through
   `module/blender_module.cpp` and the tile loop / wavefront iteration, F12
   cooperative cancel, `test_break()` honoured; measure cancel-ack p95 with
   the recorder. Then add the Phase 2 metric (UI event latency while a chunk
   renders, target p95 ≤ 33 ms) to `blender_driver.py --mode interactive`
   and measure it — that number is the owner's "UI runs at the render's
   frame rate" complaint made concrete. Design the off-main-thread session
   only after the number exists (Opus 4.8 architect + Terra); do not start
   threading code before that review.
3. **pkg237 firefly-free scene (Sonnet 5, small), then pkg255 Metallic BSDF
   support-or-warn floor (Sonnet 5).** pkg237: change only the SSIM test's
   HDRI generator per the spec's Progress note, keep 0.97, measure on the RTX,
   flip to done. pkg255 after that; pkg256 Sky / pkg257 Displacement follow
   if the round has room. pkg253's GPU alpha in the deferred shadow stage
   waits until pkg258's GPU leg has merged (same kernels).
4. **pkg259 Phase 0 (Sonnet 5 drafting + one Astra brainstorm via Codex).**
   Produce `reference-corpus-design-2026-09.md`: scene families, the
   feature-to-scene allocation table against `coverage_matrix.json`, asset
   licences, composition notes. No scenes are built until the design doc is
   in the repo and you have reviewed it; Phase 1 (`materials_hall` +
   `textures_mapping`) may start if lanes 1–3 are all blocked on the GPU.
5. **Fill work when a slot frees:** pkg242 Phase 2 real-Blender parity;
   pkg245 normal/bump provenance; pkg254 spectral path-tracer xfails.

## Per-PR flow (unchanged)

worktree → implement with tests → CPU build + focused pytest → `/lint` →
`delegate --tier verify` critique → open PR → CI → CUDA build under the GPU
lock → GPU tests + saved render → you inspect the render → `cpp-abi-guard`
if headers/signatures changed → call-site sweep → squash-merge → spec Status
flip → STATUS.md line. A numeric gate failure is investigated on both sides
(implementation and reference) before anything is re-pinned.

## Closeout (last ~90 minutes)

Merge or park with a state-of-play comment; no half-merged lane. Flip spec
statuses, add a STATUS.md top block, regenerate `KNOWN_ISSUES.md`
(`python scripts/dev/known_issues_report.py`), rebuild the index
(`python scripts/project_index.py build` + `graph --html
.astroray_plan/project-index-graph.html`), `lint --all` clean, consolidate
memory, and write the morning message: what merged (with measured numbers),
what is open, decisions the owner must make, manual owner actions. Then
write the next handoff prompt in this same format.
