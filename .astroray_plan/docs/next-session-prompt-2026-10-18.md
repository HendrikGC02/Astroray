# Next session (written 2026-10-18 morning, end of the overnight Fable-lead session)

Read first: `STATUS.md` (2026-10-18 entry), `architect-plan-2026-10-18.md` (tonight's plan; items 1–11),
`stage0-gate-scoring-2026-10-18.md`, `anthropic-agentic-practices-2026-10.md` (the rules now in CLAUDE.md §5),
`rendering-advances-research-2026-10.md` (candidate packages), memory `isolated-blender-launcher-blocks-redirected-caller`.

## State at handoff
- main `57a0c934`+: #1123 and #1138 merged; `build_cuda` and `dist/astroray` rebuilt at `3bb710b8`
  (stamped `3bb710b+20261017T134944Z`). Local main == origin/main.
- Gates: (c) GREEN formal on stamped main; (e) one open high (#1124, lane running); (a) formal driver running at
  handoff (`%LOCALAPPDATA%\astroray-evidence\2026-10-18\a\`, lock holder `lead`); (b)/(g) not re-measured.
- Open PR **#1139** pkg321 (CI pending, blind Opus review pending, GPU confirmation of the probe table pending:
  `gpu_locked_run.py lead -- python -m pytest tests/test_pkg321_dropped_row_probes.py -m gpu -q` in its worktree
  with `ASTRORAY_PYD_DIR` = a copy of `build_cuda`). Merge after both; flip the spec to done.
- Lanes (worktrees under `.claude/worktrees/`): `i1120` (Opus; 4 commits, **BUILD REQUEST d7fee170** waiting for the
  lead's `build_cuda_worktree.bat <wt> d7fee170` + the GPU commands in its report; B2 Ng check blocked by rule 13 →
  file a follow-up), `i1124` (Opus; prod_attributes GPU, started 10:30), `i1117` (Sonnet; scanner Pointiness +
  curves inner_backface, started 10:30). Resume a lane by name with SendMessage; they end turns with BUILD REQUEST.
- Lane cap 2 + lead; OMP 8 / `-j 6` for lanes; one heavy lead job at a time (8 hardware resets since 09-23).

## First jobs
1. Read the gate (a) result (`a\instrument.json`; pass p95 ≤ 100, p99 ≤ 150) and record it in the scoring doc.
2. Build `i1120` at d7fee170 (`cmd /c scripts\build\build_cuda_worktree.bat <wt> d7fee170`, no other nvcc running),
   run its GPU command list under the lock, cuobjdump REG/STACK on the principled shade kernels, resume the lane with
   the numbers; PR when `coat_over_tinted_glass` is in [0.95, 1.05] with the xfail removed and the glass suite 42/42.
3. #1139: merge on CI green + review SIGN-OFF + GPU probe confirmation. Then rebase `i1117` if it touched the scanner.
4. M2 row (g) on the merged build (`PKG310_WORK=<dir> gpu_locked_run.py lead -- pytest tests/test_production_corpus.py
   -k "parity or silent"`, then `gate_manifest.py --adapt-g`); M5 (#1123 perf, Cornell min-of-5) and M6 (glass issues
   #957/#968/#773/#1038/#954 re-measure); M7 (#721/#855 viewport re-measure). Row (e) re-reduce: fresh snapshot +
   ratings for all 69 open issues (sources: 10-04 file, 10-06 doc, 10-18 doc; Haiku join table in this session).
5. Closeout: integration branch, full CPU+GPU sweep (no `-x`, ~52 min), `run-report`.

## Owner questions (from the architect, plus tonight)
1. Keep the 2-lane cap with SMT on? (two resets on 10-14)
2. Gate (b): does the 10-06 population decision count as the b1 sign-off? pkg323 says the predicate (rect vs mask) is not
   the binding axis; the real axes are a noise-aware metric, per-identity vs per-node credit, eligibility, effect threshold.
3. Where should (a)/(c)/(g) evidence live (git, LFS, local)? Asked for the fourth time.
4. Gate (f): when can the second-PC runbook run? ZIP rebuilt tonight at `3bb710b8` (`dist/astroray-4.0.0-cuda.zip`).
5. `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` stays in `.claude/settings.json`; the research note flags named subagents
   may launch as teammates at higher token cost. Keep, or scope it to the `team-overnight` skill?
6. opencode critic did not complete twice tonight (#865); blind-Claude-only reviews were used. Acceptable while
   Codex is out (until 2026-11-04)?

## Rules that bit tonight
- A chained `launch_isolated_blender.ps1 ... *> log; driver` never reaches the driver (memory note). Verify a
  measurement is running within minutes (process list, lock holder, evidence dir).
- Lanes must not import the lead's `build_cuda` .pyd directly (relink fails on a loaded module): copy to `build_lane\`.
- New `.claude/agents/*.md` are invisible to the Agent tool until the registry refreshes; use `general-purpose` + `model:`.
