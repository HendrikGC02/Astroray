# Next-session prompt — 2026-09-13 handoff

Paste everything below the line into a fresh Claude Code (Fable 5.1) session opened in the main
checkout. Written by the outgoing lead (2026-09-12 ~10:30 → 2026-09-13 ~05:00 AEST, one usage-limit
kill at ~01:30 that killed two Opus lanes; both resumed from pushed WIP). Owner decisions it cites are
in `north-star-and-integration-gate-2026-09-07.md` §7 and STATUS.md (2026-09-12/13 block).

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside
Blender 5.2. Continue feature development and repo improvement in the same manner as the previous
lead sessions, autonomously, for a long unattended stretch. Work fast, break things behind tests,
leave a morning-readable record. **Batched lanes** (owner 2026-09-11): several independent items per
worktree / build / sweep / CI cycle, one PR per batch with per-item sections and tests.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` (north star, gate (a)–(f), §7).
3. `.astroray_plan/docs/STATUS.md` top block (2026-09-12/13) — what merged with numbers, what is held.
4. Specs: **pkg267 + pkg268** (volumes track, dispatch first), pkg266 (§9 data point: worker ON
   tick-gap PASS, present-rate UNGRADEABLE), pkg265 (Phase 3 GPU walk designed in the research note
   "Phase 3 (GPU walk) — port design"), pkg256/#799 (Phase 2 = engine-side spectral sky), pkg259 (done
   through Phase 3), the triage note `half-implemented-triage-2026-09-12.md` (which packages are
   finish-in-a-batch / parked / closed).
5. `python scripts/project_index.py whatis pkg268` etc.; `scripts/README.md` before writing any script.
6. Memory: `agent-model-alias-opus-means-opus-5` (read first), `wavefront-reuploads-scene-every-render-call`,
   `lanes-overwrite-lead-scratchpad-files`, `ssim-gate-baseline-can-encode-a-bug`,
   `gpu-lock-lanes-overwrite-lock-file`, `subagent-background-build-stall`.

## Hard constraints (owner directives — do not reinterpret)

- **Models.** Never spawn Fable subagents. Opus 4.8 lanes = `package-implementer` / `cpp-abi-guard` /
  `cycles-parity-reviewer` / `architect` definitions with the `model` parameter OMITTED; `model: "sonnet"`
  only for Sonnet 5 lanes. Grunt via `delegate.py --tier grunt --agent grunt --model
  opencode-go/glm-5.3-flash` (docs) — evidence, never trusted. **Astra and Codex were unavailable
  2026-09-12 (usage cap)** — check `codex` availability before planning Terra/Luna calls; if available:
  ≤ 4 Terra calls, Luna free, never Astra outside the owner-designated optimisation session.
- **Usage limits kill lanes** (twice this month). Every lane brief demands commit + push after each step;
  a killed lane resumes as a NEW agent with a state brief (SendMessage works in this harness for a
  LIVE lane — `SendMessage(to: <lane name>)` — but a dead lane needs a continuation agent).
- **Blender.** 9876 = owner's live instance — never touch. Isolated GUI: `scripts/dev/launch_isolated_blender.ps1
  -Port 9877 -Worker 0|1 -StateDir <dir>` (now in the repo). Headless `blender -b`. The staged + installed
  addon at closeout is from main (see Manual actions).
- **GPU.** One CUDA build / GPU verifier at a time under `.astroray_plan/.orchestrator.gpu.lock`: builds via
  `python scripts/build/gpu_locked_build.py <tree> scripts\build\build_cuda_nosccache.bat <who>` (in the repo
  now; locks the MAIN path); test runs via a loop on `acquire_lock(<MAIN lock>, 5400, meta)` from
  `scripts/roadmap_orchestrator/locks.py`, release in `finally`. Lead helpers under lead-only names
  (`lead_*.py`) — a lane overwrote the shared `gpu_locked_run.py` this session. `.pyd` mtime vs
  `git log -1 --format=%cd HEAD` before any GPU number.
- **Worktrees.** Sibling `git worktree add ../Astroray-<batch> -b <branch> origin/main`; ≤ 3 building
  lanes; remove only after MERGED + clean. `blender_addon/__init__.py` is mixed CRLF/LF — check
  `git diff --ignore-space-at-eol --stat` before review.
- **Merging.** Code: PR + CI green + GPU gate + your own render inspection + reviewers where headers /
  physics changed → `gh pr merge --squash`, verify, clean up. Pure `.astroray_plan/` docs commit to main.
- **Specs.** TEMPLATE v2; `python scripts/project_index.py lint <spec>`; Status vocabulary
  open|in-progress|blocked|paused|done|superseded.

## State you inherit (verified 2026-09-13 ~05:00)

- Merged this session: **#803 #806 #804 #805** (+ #808 if STATUS says so) — numbers in STATUS. Issues closed:
  #782 #801 #757 #796 #802 (#776 with #808). Filed: **#807** (volume cabinet → pkg268 acceptance scene).
- **Volumes track opened**: pkg267–pkg272 on main (research note `volumes-track-research-2026-09-12.md`).
  Owner questions pending: VDB import via Blender Python API vs an engine `.nvdb` reader; blackbody spectral
  Planck vs Cycles-match RGB; pkg272 scope.
- **#801 fixed** (device scene cache): viewport chunks 242 → 4.5 ms fixed cost at 200k tris; synchronous
  path tick gap now = one full-res spp (50 ms chunk budget); worker path (opt-in) 8 ms tick gaps but
  **present-rate UNGRADEABLE** (completed = 0 while the device renders) — pkg266 next lane.
- **#799**: sun disc landed (physical, sun_size-invariant irradiance, option A); absolute exposure proven
  unreachable with a bake constant (2.2× drift across elevation) → Phase 2 = engine-side spectral sky.
  Owner-visible: warm Preetham sky vs Nishita blue; ground direct:diffuse 1.8:1 vs Cycles 6.4:1.
- **#795 chrome deficit**: not multi-scatter (roughness 0.05); decisive A/B = uniform env vs HDRI through
  `benchmarks/cycles-parity/metal_ab` (posted on the issue) — do it.
- **IES normalisation fork** (documented divergence): peak-normalised vs Cycles' absolute 4π/177.83.
- pkg265 Phase 3 GPU walk: designed, not built (two strict xfails remain).
- Half-implemented triage: finish-in-a-batch = pkg253 (GPU alpha shadows), pkg201 (pkg200 driver closeout),
  pkg242 Phase 2, pkg254 xfails; fill = pkg227 (owner decision), pkg121, pkg245 (architect review).

## Dispatch order (lead's recommendation, batched)

Batch F — **volumes part 1** (Opus 4.8, cite-algorithm): pkg267 grid import + majorant (CPU-only lane) and
  pkg268 CPU heterogeneous transport + Principled Volume basics + NEE, #807 as the first cross-check scene.
Batch G — **viewport/pkg266**: root-cause present-rate UNGRADEABLE (worker terminal generation), the
  cancel p99 / present-rate rows, then the worker default decision; add a chunk-spp column to the
  `ui_latency` recorder so samples/s is measured, not inferred.
Batch H — **GPU shade-stage items**: pkg253 GPU alpha shadows + pkg254 xfails + pkg265 Phase 3 GPU walk
  (REG 254 pattern; one lane, one build).
Batch I — **parity fill**: #795 A/B, pkg242 Phase 2, pkg201 driver closeout, #773, #767, run_parity scenes
  `textured_emitter` + `sky_sun` (manifest.toml), #763 four-way variance test.
Then: #799 Phase 2 (engine-side spectral sky, cite-algorithm), pkg245 architect review, pkg227 owner decision.

## Per-batch flow

One worktree per batch → implement each item with its own tests → build + focused pytest → `/lint` →
PR → CI → CUDA build under the GPU lock → GPU tests + saved render → you inspect the render →
`cpp-abi-guard` / `cycles-parity-reviewer` where headers/physics changed → call-site sweep →
squash-merge (verify) → spec Status flip → STATUS.md line.

## Closeout (last ~90 minutes)

Merge or park with a state-of-play comment; flip spec statuses; STATUS.md top block; regenerate
`KNOWN_ISSUES.md` (`python scripts/dev/known_issues_report.py`); rebuild the index + graph; `lint --all`
clean; consolidate memory; rebuild main `build_cuda` + restage/install the addon from main; final RTX
sweep; write the morning message and the next handoff prompt in this format.
