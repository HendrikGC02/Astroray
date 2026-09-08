# Next-session prompt — 2026-09-09 handoff

Paste everything below the line into a fresh Claude Code (Fable 5.1) session opened in the main
checkout. Written by the outgoing day lead (2026-09-08, 10:00 → ~16:30); owner decisions it cites
are in `north-star-and-integration-gate-2026-09-07.md` §7, STATUS.md (2026-09-08 closeout block) and
`pkg241-phase2-offthread-design-2026-09-08.md` §8/§12.

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside
Blender 5.2. Continue feature development and repo improvement in the same manner as the previous
lead sessions, autonomously, for a long unattended stretch. Work fast, break things behind tests,
leave a morning-readable record.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` (north star, gate (a)–(f), §7).
3. `.astroray_plan/docs/STATUS.md` top block (2026-09-08 closeout) — what merged with numbers, what is
   in flight, the decisions pending.
4. Specs: pkg264, pkg241 (+ design doc §9/§12), pkg262, pkg259, pkg242, pkg245, pkg256, pkg254
   (`.astroray_plan/packages/`); docs `pkg263-rough-glass-ab-2026-09.md`,
   `pkg264-glass-energy-research.md`, `pkg258-ground-residual-diagnosis-2026-09-08.md`,
   `reference-corpus-design-2026-09.md` §6 + owner answers.
5. `python scripts/project_index.py whatis pkg264` etc.; `scripts/README.md` before writing any script.
6. Memory: `keep-worktree-until-merge-confirmed`, `landed-features-off-by-default-audit`,
   `subagent-background-build-stall` (corrected 2026-09-08), plus the 2026-09-08 morning set.

## Hard constraints (owner directives — do not reinterpret)

- **Models.** Never spawn Fable subagents. High-reasoning subagents on **Opus 4.8**
  (`package-implementer` / `cpp-abi-guard` / `cycles-parity-reviewer` definitions), never Opus 5.
  Low-level/mid work on **Sonnet 5**. Bounded grunt via `delegate.py --tier grunt --agent grunt
  --model opencode-go/glm-5.3-flash`; delegated output is evidence, never trusted.
- **Codex** is a CLI reviewer only (`codex exec -m gpt-5.6-terra -s read-only -c
  model_reasoning_effort='"high"' - < prompt.txt`, launched through a detached pwsh script — the
  bare `codex` shim is a `.ps1`; see the scratchpad pattern in STATUS), at most **4 Terra calls** this
  session; `gpt-5.6-luna` freely; **no Astra**. Never let Codex orchestrate.
- **Blender.** `pwsh scripts/dev/launch_blender_mcp.ps1 -Watch` (9876 = the owner's live instance,
  PID 1676 — never touch); isolated GUI sessions on 9877 with a disposable profile; headless `blender -b`.
- **GPU.** One CUDA build or GPU verifier at a time under `.astroray_plan/.orchestrator.gpu.lock`
  (`scripts/roadmap_orchestrator/locks.py`; acquire/poll/release-in-finally). Before any GPU number:
  `.pyd` mtime vs `git log -1 --format=%cd HEAD`. `build_cuda.bat` hits the sccache drop on
  `stage_advance.cu`; use the launcher-free `test_results/2026-09-07-setup/build_nosccache.bat` pattern.
  The main `build_cuda` .pyd is from 07:54 2026-09-08 and is STALE for engine code (#760, #766 landed
  after it) — rebuild before the first GPU gate.
- **Worktrees.** Sibling `git worktree add ../Astroray-<pkg> -b <branch> origin/main`; max 3 concurrent
  implementation worktrees; remove only after `gh pr view N --json state` says MERGED and the tree is
  clean (memory `keep-worktree-until-merge-confirmed`).
- **Lane continuity.** Every lane commits + pushes WIP after each step; a lane that goes quiet on its
  own background build usually re-wakes here — check the build/task state before spawning a
  continuation (memory `subagent-background-build-stall`). Lanes must build in the foreground.
- **Merging.** Code: PR + CI green + GPU gate + your own render inspection + the reviewer agents where
  headers/physics changed → `gh pr merge --squash` in its own command, verify, then clean up. Pure
  `.astroray_plan/` docs may commit directly to main — but batch them while feature PRs are in CI
  (every main commit puts waiting PRs behind and costs a merge round).
- **Specs.** TEMPLATE v2; `python scripts/project_index.py lint <spec>`; Status `done — <text>`.
- **Keep `test_results/`** untouched except regenerable caches. Design help: real tradeoff axes, no ballots.

## State you inherit (verified 2026-09-08 ~16:30)

- main at the closeout commit; merged today #754 #756 #758 #760 #761 #764 #766 #768 #771 (numbers in STATUS; run report `reports/2026-09-08-day-lead-session.html`).
- **pkg264 done (#771)** but the ±5 % rough-glass parity criterion is NOT met: residual re-scoped to **#770**
  (reject + correct `energy_scale` instead of the delta reroute, why `ggxGlassComp` alone leaves 0.645, a glass
  scene in `scripts/run_parity.py`). No worktrees remain.
- Viewport: Phase 2 design Rev 4 lead-verified; A2 spike merged flag-gated (#768) with the A2
  decision in design §12; **P2.2 scope = §12 items 1–5** (present wiring, bounded incremental commit,
  cancel-ack through the pump, settle-window instrument, `gpu.types.Buffer` upload for the
  synchronous path).
- Corpus: Phase 1 merged (#761); Phase 1 polish (hall reframe + per-alcove crops) and Phase 2
  (`lighting_studio` + `world_sky`) are CPU-only builder work.
- Open P1 issues: #759 (GPU adaptive inert), #762 (texture → Emission blank), #769 (addon zip lacks
  the compensation tables — gate (f)); P2: #755, #757, #763, #767; P3: #765.
- Codex Terra calls remaining today's budget resets per session (4).

## Dispatch order (lead's choice; owner delegated it)

1. **#770 rough-glass residual** (Opus 4.8, cite-algorithm; file it as pkg265 first): the Cycles-faithful
   reject + `microfacet_ggx_preserve_energy` mechanism replacing the delta reroute on both lobes, gated by a
   directional test + the pkg263 harness (target ±5 %); add the run_parity glass scene. The owner's named complaint.
2. **pkg241 P2.2** (Opus 4.8, design §12 items 1–5; Terra 1 call on the P2.2 diff is worth it): first
   the present-wiring bug + `gpu.types.Buffer` for the synchronous path (both quick, both visible),
   then the bounded incremental commit and the settle-window gate; measure with `--mode ui_latency`.
3. **pkg262** (Sonnet 5 → Opus 4.8 if the A/B gets subtle): the GPU adaptive effect test first (red on
   main), then the flips with the pkg81 bench + parity sweeps.
4. **#769 addon data-table packaging** (Sonnet 5, small, gate (f)) and **#762 Emission texture**
   (Sonnet 5, addon + closure-graph lowering) — independent of the GPU lock except the GPU parity test.
5. **pkg259 Phase 1 polish + Phase 2** (Sonnet 5 builders, CPU) in parallel with the above.
6. Fill: pkg256 Sky (cite-algorithm), pkg242 Phase 2, pkg245, pkg254; #757, #765.

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
