# Next-session prompt — 2026-09-24 handoff

Paste everything below the line into a fresh Claude Code session (Opus 5.5) opened in the main checkout.
Written by the 2026-09-23/24 supervisor session (Opus 5.5 supervising Astra; Astra ran out of Codex usage).

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside Blender 5.2.
Continue development autonomously in **batched lanes** (owner 2026-09-11). You have commit, push, PR and
merge authority once the documented gates and independent reviews pass.

## Model availability this session

- **Codex is unavailable** (Terra, Luna and Astra all hit the usage limit, which resets 2026-09-27 23:30). Don't call
  `codex exec`.
- **Claude usage has reset.** Opus 5.5 is the judgment tier and the lead: specs, physics parity, ABI
  reachability, gate-failure root cause, merge decisions, visual inspection. Sonnet 5 is the grunt and second-
  lineage reviewer seat Terra used to fill; Haiku 4.5 summarises files. **Never Fable.**
- **opencode**: DeepSeek V4.1 Flash (`opencode-go/deepseek-v4.1-flash`) is the implement + grunt primary
  (fallback deepseek-v4-pro; glm-5.3-flash for docs). Use it via the `delegate` skill in isolated
  worktrees; verify every diff with build + pytest + `lint`. Hard multi-file physics/shade-kernel work
  stalls on it — give that to an Opus 5.5 lane.
- Independent-review rule: an implementer's work is reviewed by a different lineage (Opus lane → Sonnet or
  deepseek-v4-pro critic; Flash lane → Opus/Sonnet reviewer).

## Read first (in this order, then start)

1. `CLAUDE.md` (§5 model policy, §5b no duplicate scripts, §6 cite algorithms, Build & Verification),
   `AGENTS.md`. Run `python scripts/project_index.py {query,owns,whatis,deps,script}` before grepping
   `.astroray_plan/` or `scripts/`.
2. `.astroray_plan/docs/next-session-prompt-2026-09-23.md` (the prior handoff: batch order and method).
3. `.astroray_plan/docs/stage-plan-2026-09-22.md`, `.astroray_plan/docs/STATUS.md` top block.
4. Astra's run log and prep, outside the repo in `C:\Users\hgcom\OneDrive\Astroray\astra_run\`:
   `progress.md` (## CURRENT, ## NEEDS OWNER, EVENTS), `batchU-readiness.md`,
   `batchU-{845,851,852,859}-*-preflight.md`, `pkg278-remaining-audit.md`,
   `pkg278-clean-host-producer-plan.md`. They're already researched, so reuse them rather than redoing them.
5. Memory: `lead-runs-builds-lanes-never-poll`, `concurrent-nvcc-builds-kill-each-other`,
   `sccache-drops-long-cuda-compiles`, `verify-attribution-with-a-baseline-build`,
   `ci_has_no_gpu_runtime_blindspot`, `never-kill-by-commandline-match`, `gpu-lock-lanes-overwrite-lock-file`,
   `usage-limit-kills-agents-commit-wip-early`, `concise-writing-style`, `no-fable-agents`.

## State you inherit (2026-09-24)

- Main at `be340452`. No open PRs. Five unrelated modified `test_results/batchF|batchK/*.png` in the main
  checkout — leave them.
- **Batch A merged (#870)** — pkg278 exit-gate instruments checkpoint + #823 scanner. Gates measured:
  A/C/D/E RED, B provisional (nine-scene corpus not yet ratified), F unmeasured (no clean Windows host).
  pkg278 stays OPEN; remaining items in `astra_run\pkg278-remaining-audit.md`.
- **Batch B merged (#871)** — pkg280 done (fixed stop). Thin-disk `g⁵·B_λ(gλ)` transfer landed and validated;
  ~15× GR render time = PR #405 scene settings, not code. **Kerr vs GYOTO failed**: engine ignores `spin`
  (always Schwarzschild) and `redshiftFactor` ignores photon momentum → no GR path science-ready.
  Follow-ups filed: **pkg281** (Kerr spin), **pkg282** (momentum redshift + pkg107 0.37× shadow-size
  offset), **pkg283** (ADAF/synchrotron invariant transport). GYOTO 2.0.2 is built in WSL at
  `/home/hgcom/pkg280-external` (GPL: external executable only).
- Full suite on the Batch B build: 3268 passed / 0 failed on the RTX 5070 Ti.
- Leftover worktrees `Astroray-batchA-*`, `Astroray-batchB-transfer`, `Astroray-batchH`,
  `Astroray-pkg280-may-baseline`: prune the ones whose branches are merged (confirm on origin/main first).

## Dispatch order

1. **Batch U — light-transport correctness:** #859, #851/#763, #852, #860/#833/#842, #845. Each needs a
   named observable, fixture, threshold and evidence owner BEFORE dispatch; start from Astra's
   `batchU-*.md` preflights.
2. **Batch V — viewport:** #857, #854/#855/#856, then #849 only as far as the gate (a) table demands.
   Owner try-out (#858) comes before any default flip. Close #721 on the measured table.
3. **Batch Y — coverage:** #846, pkg277 (#822), #847. Finish the remaining pkg278 items where they are unblocked.
4. **GR correctness (Pillar-4 groundwork):** pkg281 → pkg282 (CPU; GYOTO gates). pkg283 after them.
5. When the queue runs out, have an Opus architect lane draft a vetted next set from the stage plan and keep going.

## Operating rules (non-negotiable)

- You, the lead, run every CUDA build, one at a time, in the background, under the GPU lock:
  `python scripts/build/gpu_locked_build.py <worktree> <wrapper.bat> <who>` where the wrapper calls
  `scripts\build\build_cuda_worktree.bat <worktree> <full-40-char-sha>`. Build without sccache for long
  CUDA compiles: take `WinGet\Links` off PATH and put a copied `ninja.exe` first. Confirm the sm_120
  arch-verify line and the `.pyd` mtime. Lanes never build CUDA and never poll builds.
- Full suite: `python scripts/build/gpu_locked_run.py <who> -- python scripts/dev/run_tests.py --build-dir
  <wt>\build_cuda --temp-dir <tmp> -- tests -q --tb=short -rXf -p no:cacheprovider` (~35 min, no `-x`).
- Commit explicit paths only. Check `git diff --ignore-space-at-eol --stat`. Merge with
  `gh pr merge --squash` after CI is green, then confirm origin/main moved before removing a worktree.
- Visually meaningful changes: save renders and inspect them yourself. Attribute failures against a
  baseline build of origin/main, never by reasoning about the diff.
- Lanes commit WIP early (usage limits kill lanes mid-run) and keep evidence under
  `C:\Users\hgcom\OneDrive\Astroray\astra_run\<batch>\`.
- Keep `astra_run\progress.md` current (one dated line per event; ## CURRENT at top) so Astra can resume
  from it when Codex returns.

## Owner decisions still outstanding (don't make them yourself)

- Ratify the nine-scene corpus as the gate (b) population (stage plan §6).
- Default flips after the owner try-out (#858).
- Showcase-scene ask: glass dispersion + caustics, volumes, Nishita sky + sun, thin film + metals, and a
  black hole (only after pkg281/282, since GR is not yet correct). Do these when a lane slot is idle.

At the end, write `next-session-prompt-<date>.md`, update STATUS.md, and produce a `run-report`.
