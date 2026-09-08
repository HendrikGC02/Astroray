# Next-session prompt — 2026-09-10 handoff

Paste everything below the line into a fresh Claude Code (Fable 5.1) session opened in the main
checkout. Written by the outgoing overnight lead (2026-09-09, 00:30 → ~07:50); owner decisions it
cites are in `north-star-and-integration-gate-2026-09-07.md` §7 and STATUS.md (2026-09-09 closeout).

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside
Blender 5.2. Continue feature development and repo improvement in the same manner as the previous
lead sessions, autonomously, for a long unattended stretch. Work fast, break things behind tests,
leave a morning-readable record.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` (north star, gate (a)–(f), §7 —
   the 2026-09-08 evening block carries the **physics-first engine-wide rule**).
3. `.astroray_plan/docs/STATUS.md` top block (2026-09-09 closeout) — what merged with numbers, what is
   in flight, the decisions pending.
4. Specs: **pkg265** (+ research note `pkg265-multiscatter-microfacet-research.md` Phases 4–7 and the
   review comments on PR #778), **pkg266**, pkg262, pkg259, pkg241 (design doc §12/§13/§13a), pkg242,
   pkg245, pkg256, pkg254; docs `pkg263-rough-glass-ab-2026-09.md`, `reference-corpus-design-2026-09.md`.
5. `python scripts/project_index.py whatis pkg265` etc.; `scripts/README.md` before writing any script.
6. Memory: `gpu-lock-lanes-overwrite-lock-file`, `unbiased-strategy-switch-moving-a-mean-is-a-bug-signal`,
   `clean-room-oracle-is-self-consistency-not-ground-truth`, `codex-exec-output-is-full-transcript`,
   `keep-worktree-until-merge-confirmed`, `landed-features-off-by-default-audit`.

## Hard constraints (owner directives — do not reinterpret)

- **Models.** Never spawn Fable subagents. High-reasoning subagents on **Opus 4.8**
  (`package-implementer` / `cpp-abi-guard` / `cycles-parity-reviewer` definitions), never Opus 5.
  Low-level/mid work on **Sonnet 5**. Bounded grunt via `delegate.py --tier grunt --agent grunt
  --model opencode-go/glm-5.3-flash`; delegated output is evidence, never trusted.
- **Codex** is a CLI reviewer only (`codex exec -m gpt-5.6-terra -s read-only -c
  model_reasoning_effort='"high"' - < prompt.txt` via a one-line `.ps1` run in the background; the output
  is a ~1 MB transcript — take the LAST `^VERDICT:` line), at most **4 Terra calls** this session;
  `gpt-5.6-luna` freely; **no Astra**. Never let Codex orchestrate.
- **Blender.** `pwsh scripts/dev/launch_blender_mcp.ps1` (9876 = the owner's live instance — never
  touch); isolated GUI sessions on 9877 with a disposable profile (the `mcp` extension's autostart races
  the port reassignment — start the bridge on 9877 synchronously, see SUMMARY.md of P2.2); headless
  `blender -b`. **Addon CPU renders are single-threaded (#780)** — budget corpus renders accordingly.
- **GPU.** One CUDA build or GPU verifier at a time under `.astroray_plan/.orchestrator.gpu.lock`:
  lanes must LOOP `acquire_lock(path, 5400, meta)` from `scripts/roadmap_orchestrator/locks.py` and
  NEVER write the lock file (a lane did on 2026-09-09 and measured during a CUDA build). Before any
  GPU number: `.pyd` mtime vs `git log -1 --format=%cd HEAD`. Build with the launcher-free
  `test_results/2026-09-07-setup/build_nosccache.bat` pattern through the lock wrapper
  (scratchpad `gpu_locked_build.py` pattern: poll, run, release in finally). The main `build_cuda`
  .pyd is from 07:18 2026-09-09 at 1108b918 (post-#777) — fresh.
- **Worktrees.** Sibling `git worktree add ../Astroray-<pkg> -b <branch> origin/main`; max 3 concurrent
  implementation worktrees; remove only after `gh pr view N --json state` says MERGED and the tree is
  clean. Being behind main does NOT block `gh pr merge --squash`.
- **Lane continuity.** Every lane commits + pushes WIP after each step (two usage-limit kills last night;
  one lane had never committed); lanes re-wake on their own background builds — check `git log`/process
  state before spawning a continuation. Lanes must build in the foreground. Check
  `git diff --ignore-space-at-eol --stat` before review — three lanes normalised line endings on
  700-line files last night.
- **Merging.** Code: PR + CI green + GPU gate + your own render inspection + the reviewer agents where
  headers/physics changed → `gh pr merge --squash`, verify, clean up. Pure `.astroray_plan/` docs may
  commit directly to main.
- **Specs.** TEMPLATE v2; `python scripts/project_index.py lint <spec>`; Status `done — <text>`.
- **Keep `test_results/`** untouched except regenerable caches. Design help: real tradeoff axes, no ballots.

## State you inherit (verified 2026-09-09 ~07:50)

- main at the closeout commit; merged last night **#774 #775 #777 #781** (numbers in STATUS; run report
  `reports/2026-09-09-overnight-lead-session.html`).
- **PR #778 pkg265 CPU leg — OPEN, HELD** (`feat/pkg265-ms-microfacet-glass`, worktree
  `../Astroray-pkg265gpu`; the stochastic-eval lane may still be pushing there — check `gh pr view 778`
  comments and `git log` before touching the branch).
  State: Heitz 2016 walk clean-room (Option A — supplemental licence-unstated, Mitsuba GPLv3), oracle,
  directional gate 41/41, furnace in band, delta reroutes removed; TWO parity reviews: (1) eval/NEE
  single-scatter vs walk sample → fixed by a skip-NEE delta contract, which moved the pkg263 harness
  limb 1.05 → **0.60** of Cycles (centre 1.52 → 0.93) — inconsistent, NOT mergeable; (2) thin-film rough
  glass double-counted — fixed (f6c06fa5, film glass stays single-scatter; thin-film-aware walk → #783).
  **Lead decision recorded on the PR:** implement the paper's stochastic eval (Eq 42, `msdiel::stochasticEval`)
  with a **hash-seeded RNG** (pbrt-v4 `LayeredBxDF::f` pattern, Apache-2.0, pure function of wo/wi, no
  signature change), `isDelta=false` again, pdf = §9 proxy; re-run the pkg263 harness (Phase 8), lit
  furnace, directional gate; then parity re-review + ABI, rebase, merge. Independent oracle → **#782**
  (explicit heightfield) before any "physical divergence" claim. GPU leg = Phase 3 (later, REG 254).
- **pkg241 P2.2 done (#777)**; residual gates in **pkg266** (cancellation-bounded wavefront dispatch,
  coalesced dirty-domain commit, global admission token, clean re-measure). Worker still opt-in.
- **pkg259**: Phase 1 polish merged (#781); Phase 2 (`lighting_studio` + `world_sky`) not started;
  CC0 HDRI already in `benchmarks/reference_corpus/assets/`.
- **pkg262 not started** (no worktree slot all night). Fresh main .pyd available.
- Open issues filed last night: #773 (addon r0 glass limb −15 %), #776 (textured-emitter NEE),
  #779 (run_parity .blend Astroray leg is base-colour-only — the glass row is a diffuse proxy),
  #780 (addon CPU single-threaded — OpenMP disabled for the old MinGW deadlock; MSVC vcomp may be safe),
  #782 (independent multi-scatter oracle). Older P1: #759 (GPU adaptive inert → pkg262), #721 (→ pkg266).
- Codex Terra: 4 calls available this session.

## Dispatch order (lead's recommendation)

1. **pkg265 stochastic eval → land #778** (Opus 4.8, `cite-algorithm`: Heitz 2016 §8.1 + pbrt-v4
   `LayeredBxDF` hash-seeded RNG). Gate: lit furnace [0.97, 1.02] with NEE on AND off within noise;
   directional gate; pkg263 harness centre/limb recorded as the band with the mechanism explained;
   reviewers MERGE. The owner's named complaint — do not hand over a limb at 0.60 again.
2. **pkg262** (Sonnet 5 → Opus 4.8 if subtle): the GPU adaptive effect test RED on main first, then the
   flips with the pkg81 bench + parity sweeps; A/B doc with the equal-spp RMSE ratio per corpus scene (#763).
3. **pkg266** (Opus 4.8; one Terra call on the native dispatch diff): bounded wavefront dispatch under
   the GPU lock, then the coalesced commit; re-measure with the Terra-4 instrument on an idle GPU.
4. **pkg259 Phase 2** (Sonnet 5, CPU; budget the single-threaded renders — small resolutions, #780).
5. **#780** (Sonnet 5, small): test whether MSVC-built addon .pyd + vcomp OpenMP deadlocks in Blender;
   if not, enable behind a headless multi-thread canary — a 10–16× CPU render speedup for every harness.
6. Fill: pkg256 Sky (cite-algorithm), pkg242 Phase 2, pkg245, pkg254; #757, #776, #779, #773.

## Per-PR flow (unchanged)

worktree → implement with tests → build + focused pytest → `/lint` → `delegate --tier verify`
critique → PR → CI → CUDA build under the GPU lock → GPU tests + saved render → you inspect the
render → `cpp-abi-guard` / `cycles-parity-reviewer` where headers/physics changed → call-site sweep →
squash-merge (verify) → spec Status flip → STATUS.md line.

## Closeout (last ~90 minutes)

Merge or park with a state-of-play comment; flip spec statuses; STATUS.md top block; regenerate
`KNOWN_ISSUES.md`; rebuild the index + graph; `lint --all` clean; consolidate memory; write the
morning message (what merged with numbers, what is open, owner decisions, manual actions) and the
next handoff prompt in this format.
