# Next-session prompt — 2026-09-23 handoff

Paste everything below the line into a fresh Claude Code session opened in the main checkout. Written by
the 2026-09-22 planning session (Fable 5.1 lead + GPT-6 Astra co-planner + Codex Terra reviews). No engine
code changed; policy, plan and specs did.

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside Blender 5.2.
Continue feature development and repo improvement autonomously in **batched lanes** (owner 2026-09-11).

## Read first (in this order, then start)

1. `CLAUDE.md` §5 "Model policy" (owner 2026-09-22: Opus 5 judgment tier, DeepSeek V4.1 Flash implement +
   grunt primary, Codex Terra reviews AND implements with no cap, Astra fenced, Fable subagents banned,
   project index before grep — the `index_nudge` hook reminds you), `AGENTS.md`.
2. `.astroray_plan/docs/stage-plan-2026-09-22.md` — the stage plan (Stage 0 wrap-up → Stage 1 Pillar 4
   groundwork in overlap → Stage 2 thaw round 1 → Stage 3 instrument/ingest → Stage 4 validation).
3. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` §1–§2, §7 (north star, gate rows).
4. `.astroray_plan/docs/STATUS.md` top block (2026-09-22 CURRENT).
5. Memory: `opus-5-is-the-agent-judgment-tier`, `deepseek-v41-flash-implement-and-grunt-primary`,
   `codex-terra-reviews-and-implements`, `project-index-first`, `no-fable-agents`,
   `lead-runs-builds-lanes-never-poll`, `verify-attribution-with-a-baseline-build`,
   `ci_has_no_gpu_runtime_blindspot`, `concise-writing-style`.
6. Open specs to dispatch: **pkg278** (exit-gate instrumentation, Stage 0a — FIRST), **pkg280** (GR transfer
   & reference audit, the one Stage 1 groundwork lane, CPU), pkg277 (#822), pkg251 → pkg243 (Phase 1 now
   carries the length/emissivity normalisation contract).

## State you inherit (2026-09-22)

- Main at the planning-session closeout commit; no open PRs; `build_cuda` .pyd from 2026-09-20 (only docs
  landed since; still current for engine code). RTX sweep 899/0 on 2026-09-20.
- Reference bank on main: adaf/synchrotron PASS; gr-kerr / gr-schwarzschild fail SSIM only (0.93/0.85,
  unchanged since 2026-09-03, visually identical); cornell-mini self-test failing since 2026-09-06 (SSIM
  0.38). Re-baselining is pkg280 Phase 4 (attributed + independently signed off), not a quick fix.
- GR scenes take ~20 s each on CPU vs ~2 s in 2026-05 — unattributed; pkg280 Phase 2 owns attribution.
- Exit gate: (a) AMBER, (b) UNMEASURED (no weighted scorer exists), (c) AMBER, (d) AMBER, (e) RED (#721),
  (f) AMBER. pkg278 builds every instrument; measured RED is an acceptable pkg278 result.
- Pillar 4 specs rewritten and Terra-reviewed: pkg45, pkg46 (+#144), pkg48, pkg49, pkg50, pkg51 (+pkg133
  superseded), pkg107 done, pkg259 superseded into pkg278, new pkg278/pkg279/pkg280.

## Recommended dispatch order

Batch A — **pkg278** (CPU lane; RTX + clean-machine slots for the measurements) in parallel with **#823**
  (scanner blind to `_compile_socket_value`; gate (b) is not scored until it lands).
Batch B — **pkg280** (CPU, one lane, fixed stop at the evidence report).
Batch U — light-transport correctness: #859, #851/#763, #852, #860/#833/#842, #845 — each with a named
  observable, fixture, threshold and evidence owner BEFORE dispatch.
Batch V — viewport: #857, #854/#855/#856, then #849 only to the extent the gate (a) table demands; owner
  try-out (#858) before any default flip; close #721 on the measured table.
Batch Y — coverage: #846, pkg277 (#822), #847.
Then the Astra speed/noise session (Stage 0e) once pkg278 has a manifest.

**Owner decision outstanding:** ratify the nine-scene corpus as the gate (b) population (stage plan §6).
**Owner ask still outstanding:** one or two pretty Blender showcase scenes (glass dispersion + caustics,
volumes, Nishita sky + sun, thin film + metals, a black-hole scene — the GR path renders).

## Method that worked (keep it)

- Lead runs every CUDA build in the background; lanes never poll. Flash critic pass on every lane diff
  (diff inlined); Opus reviewers per PR through a Workflow; Flash or deepseek-v4-pro applies agreed
  fixes; Terra as the second-lineage reviewer now that all Claude agents are Opus 5.
- Spec drafting: Flash drafts from a tight brief (one file, template rules, lint), Terra reviews with
  ONE controlling question, Flash applies the defect list, lead verifies + commits. 2026-09-22: 13 Terra
  reviews + 24 Flash jobs for ≈ US$0.02 of opencode spend.
- Every Codex output is UTF-16 when redirected from PowerShell; decode before reading; take the LAST
  `VERDICT:` line.
