# Next session — handover 2026-09-27

You are the Astroray lead (Claude Opus 5.5). **Codex (Astra, Terra, Luna) and opencode are
available again** — limits reset. The owner may be away; work autonomously.

## First: a short architect run (owner directive 2026-09-27)
Before any implementation, run a **short architect session: Fable (the architect agent,
`model: fable` — authorised for architect runs) brainstorming with Astra (`gpt-6-astra`)**.
Goal: lay out the near-future plan so development runs smoothly and efficiently.
- Inputs: STATUS.md top entry, `architect-plan-2026-09-27.md` (batches AD..AJ; AD, AE, AF and
  pkg292 #876/#862 have landed), the open-issue list, the run report
  `reports/2026-09-27-night-shift.html`, and owner decisions below.
- Output: a revised ordered plan (batches of 3–5 items, conflict keys, GPU vs CPU, gates), specs
  for anything new, lint-clean, one docs PR. Keep it short: hours, not a night.
- Suggested questions for the brainstorm: order of the reference re-bless (pkg285) vs corpus v2
  (pkg284) now that transport fixes have settled; the remaining GPU/CPU gaps (#853 hair, #933
  partial-transmission Disney, #934 metal −15 % vs Cycles, #889 second half); viewport gate (a)
  (pkg291); how to split work across Astra/Terra/Opus/DeepSeek for cost and throughput.

## State
- main: see `git log -1 origin/main` (≥ #936). Stable CUDA build + staged addon were produced at
  the end of the last session from final main (`build_cuda/`, `dist/astroray/`).
- Last session: 17 PRs (2 Astra, 15 Claude); suite 3252 → ~3640 passing on RTX 5070 Ti.

## Operating model (proven; details in `.astroray_plan/docs/lane-rules.md`)
- Batched lanes in sibling worktrees; the lead runs every CUDA/addon build with
  `python scripts/build/lead_build_queue.py <lane>[:addon-cuda]`, one build per background task;
  lanes never build CUDA or poll.
- Independent review from a different model family for every lane: Codex Terra now (was
  deepseek-v4-pro via the `delegate` skill; split diffs over ~800 lines).
- Measure shade/intersect kernel registers after GPU changes (cuobjdump, compare to the parent build).
- Attribute failures against a baseline build; stale tests are corrected, never obeyed.
- Machine load: GPU suite never overlaps a build; ≤2 CPU-heavy lanes; OMP 8, `-j 6`.
- After a batch is squash-merged, merging main into a stacked child conflicts on duplicated
  content: verify identical, resolve ours; never regex-union whole docs.
- PR bodies: one closing keyword per issue.
- Known: `test_pkg258_env_nee_gpu_byte_identity` fails on any branch whose sampling differs from
  the current main build; it passes once main is rebuilt.

## Owner decisions (list, don't make)
Caustic boost default 1.2 → 1.0 (1.0 is physical after pkg286); gate (c) trio remap onto corpus
v2; #858 default flips (viewport worker, progressive sampler, GPU light tree); #833 engine volume
stack vs DEGRADED report.
