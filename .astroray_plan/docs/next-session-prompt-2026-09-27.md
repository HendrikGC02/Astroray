# Next session — 2026-09-27

You are the Astroray lead (Claude Opus 5.5). Work autonomously; the owner may be away.

## State
- main = 9330e5d7 (Batch AE merged). STATUS.md top entry and the run report
  (`reports/2026-09-27-night-shift.html`) describe the last session.
- Plan of record: `.astroray_plan/docs/architect-plan-2026-09-27.md` (batches AD..AJ;
  AD and AE landed). Specs pkg284–pkg293.
- In flight (branches pushed, not merged):
  - `feat/925-volume-segment-nee` (33fec409): #925 CPU per-segment volume NEE +
    bounded-medium lamp-hit fix. Needs a CUDA build, GPU run of the medium suites,
    full suite, PR. GPU twin = #929. The full-channel variance gate stays strict-xfail on B.
  - `fix/848-hero-lambda-refit` (lane af2): hero-λ proposal / blue-channel variance.
    Combine with #925 as Batch AF.

## Operating rules (unchanged unless the owner says otherwise)
- Batched lanes in sibling worktrees; the lead runs every CUDA build (queue script,
  one per background task); lanes never build CUDA or poll. `astra_run\batchU\LANE_RULES.md`.
- Independent review from a different model family per lane (opencode deepseek-v4-pro
  works; split large diffs — it runs out of tokens above ~800 lines).
- Attribute failures against a baseline build. Stale tests calibrated on a broken engine
  are corrected in the same PR (owner rule 2026-09-26).
- Machine load: GPU suite never overlaps a build; ≤2 CPU lanes; OMP_NUM_THREADS=8,
  MinGW `-j 6` (two hardware resets on 2026-09-26).
- After a merge of a squashed batch, merging main into the next batch branch conflicts
  on duplicated content: verify `git diff <prev-batch-tip> origin/main` is empty, then
  resolve with ours.
- PR bodies: one closing keyword per issue ("Closes #a, closes #b").
- Fable: banned except the end-of-queue architect run (owner 2026-09-25).

## Next
1. Batch AF: #925 (+ #848 lane) → build, GPU medium suites, full suite, PR.
2. Architect order: #929 GPU volume NEE; AF GPU/CPU divergence (pkg292 #876/#862/#853,
   pkg293); AG references (pkg284 corpus v2, pkg285 bank re-bless incl. stale ADAF pHash
   and jet coverage gates); AH viewport (pkg291); AI GR + textures; AJ tooling.
3. Also filed this session: #920, #921 (addon area lamp 0.85× Cycles), #922, #924 (lamp
   pass-through cap 4), #926.

## Owner decisions (list, don't make)
Caustic boost default 1.2 → 1.0; gate (c) trio remap onto corpus v2; #858 default flips;
#833 engine volume stack vs DEGRADED report.
