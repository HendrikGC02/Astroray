# Next-session prompt — 2026-09-14 handoff

Paste everything below the line into a fresh Claude Code (Fable 5.1) session opened in the main
checkout. Written by the outgoing lead (2026-09-13 ~08:00 → ~22:30 AEST, two usage-limit kills at
~10:xx and ~14:xx; all five lanes resumed from their transcripts via SendMessage). Owner decisions it
cites are in `north-star-and-integration-gate-2026-09-07.md` §7 (2026-09-13 block) and STATUS.md.

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside
Blender 5.2. Continue feature development and repo improvement in the same manner as the previous
lead sessions, autonomously, for a long unattended stretch. Work fast, break things behind tests,
leave a morning-readable record. **Batched lanes** (owner 2026-09-11): several independent items per
worktree / build / sweep / CI cycle, one PR per batch with per-item sections and tests.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` (north star, gate (a)–(f), §7 incl. the 2026-09-13 decisions).
3. `.astroray_plan/docs/STATUS.md` top block (2026-09-13 CURRENT) — what merged with numbers, what is parked.
4. The run report `.astroray_plan/docs/reports/2026-09-13-two-sessions.html` (both sessions, with renders).
5. Specs: **pkg270** (blackbody spectral Planck + per-λ σ; owner: own spectral Planck), **pkg269** (GPU wavefront
   heterogeneous stage, NanoVDB device grid), pkg271, pkg272 (optional); pkg266 (done — storm-row follow-up),
   pkg254 (four honest xfails), pkg265 (Phase 3 GPU walk WIP on `feat/batch-h2-pkg265-gpu-walk`,
   `.astroray_plan/docs/pkg265-phase3-gpu-walk-WIP-STATE.md`); issues **#814** (sun-disc 1.48× + IES spot
   composition), **#807** (volume cabinet), #721 (viewport storm row), #767, #763, #779.
6. `python scripts/project_index.py whatis pkg270` etc.; `scripts/README.md` before writing any script.
7. Memory (read first): `agent-model-alias-opus-means-opus-5`, `continuing-agents-without-sendmessage` (SendMessage
   RESUMES killed lanes now), `gpu-lock-lanes-overwrite-lock-file` (locks.py aa695ce5 addendum),
   `codex-reviewer-only` (Codex credits exhausted until 2026-09-20), `blender-sky-sources-apache-mit-not-gpl`,
   `wavefront-reuploads-scene-every-render-call`, `lanes-overwrite-lead-scratchpad-files`.

## Hard constraints (owner directives — do not reinterpret)

- **Models.** Never spawn Fable subagents. Opus 4.8 lanes = `package-implementer` / `cpp-abi-guard` /
  `cycles-parity-reviewer` / `pr-reviewer` / `architect` definitions with the `model` parameter OMITTED;
  `model: "sonnet"` only for Sonnet 5 lanes. **Codex is out of credits until 2026-09-20** — do not plan
  Terra/Luna calls; use `pr-reviewer` as the independent review. Astra only in the owner-designated
  optimisation session.
- **Usage limits kill lanes** (four times in two days). Every lane brief demands commit + push after each
  step; when a lane is killed, `ToolSearch("select:SendMessage")` and send the lane NAME a state brief
  (pushed commits, .pyd mtime vs HEAD, lock state, no PR yet) — it resumes with context. Never end a turn
  waiting on a background build (poll in bounded foreground chunks).
- **Blender.** 9876 = owner's live instance — never touch. Isolated GUI: `scripts/dev/launch_isolated_blender.ps1
  -Port 9877 -Worker 0|1 -StateDir <dir>`. Headless `blender -b`. The staged + installed addon at closeout is
  from main b81cbe7a (`--backend cuda`; #815 `__del__` fix included). Lanes that `--install` a worktree addon must say so; restage main at closeout.
- **GPU.** One CUDA build / GPU verifier at a time under `.astroray_plan/.orchestrator.gpu.lock` (MAIN path):
  builds via `python scripts/build/gpu_locked_build.py <tree> scripts\build\build_cuda_nosccache.bat <who>`;
  test runs via an `acquire_lock(<MAIN lock>, 5400, meta)` loop, release in `finally`, never write the lock
  file. `locks.py` now treats a dead holder pid as stale and only removes a lock the process owns. Lead helpers
  under `lead_*` names in the session scratchpad. `.pyd` mtime vs `git log -1 --format=%cd HEAD` before any
  GPU number; canary `hasattr(astroray, <new binding>)`.
- **Worktrees.** Sibling `git worktree add ../Astroray-<batch> -b <branch> origin/main`; ≤ 3–4 lanes;
  remove only after MERGED + clean. `blender_addon/__init__.py` is mixed CRLF/LF — check
  `git diff --ignore-space-at-eol --stat`. STATUS.md and specs are CRLF — patch with read_bytes/write_bytes.
- **Merging.** Code: PR + CI green + GPU gate + your own render inspection (lanes' contact sheets can be flipped
  or non-like-for-like — look before trusting) + `cpp-abi-guard` / `cycles-parity-reviewer` where headers /
  physics changed → `gh pr merge --squash`, verify, clean up. Pure `.astroray_plan/` docs commit to main.
- **Specs.** TEMPLATE v2; `python scripts/project_index.py lint <spec>`; Status vocabulary
  open|in-progress|blocked|paused|done|superseded.

## State you inherit (verified 2026-09-13 ~22:30)

- Merged this session: **#809 #810 #811 #812 #813** + **#815** (addon `__del__` shutdown noise fix, after a PC restart). Filed **#814**. Specs flipped: pkg267,
  pkg268, pkg201, pkg253, pkg266 → done; pkg242, pkg254 → in-progress with the remaining items named.
- **Volumes**: CPU heterogeneous transport is live from Blender (OpenVDB via the bundled `openvdb` module;
  Principled Volume / Absorption / Scatter with Cycles coefficient semantics; scalar σ_t, spectral albedo).
  Limitations recorded: equiangular sampling is oracle-only, nearest-medium-only in-scatter, no GPU (pkg269),
  no emission (pkg270). #807 cabinet A/B on the restaged addon: yellow disc gone, absorption/scatter cubes translucent, the Principled cube dark because Cycles' red patch is EMISSION (pkg270) — #807 open until pkg270.
- **Viewport**: off-main-thread worker is the DEFAULT (owner may veto with `ASTRORAY_VIEWPORT_WORKER=0`);
  settle gates all pass; the continuous edit storm is 159 / 175 ms (commit cost) — the pkg266 follow-up.
- **Sky**: engine-side Nishita (Apache/MIT vendored) with a model-consistent sun disc; hue and shadow direction
  match each other; but the disc/sun DIRECTION still differs from Cycles (owner-spotted 2026-09-14: cube shadows fall right in ours, left in Cycles) so the "1.48× over" gate-2 number is invalid — #814 is a direction bug first. PREETHAM / HOSEK types still use the Preetham bake.
- **IES**: absolute photometry (4π/177.83, Strength honoured), CPU-only on the wavefront (point_light.cpp v1 gap).
- **GPU alpha shadows**: all light types; REG 254 held.
- pkg265 Phase 3 GPU walk: device header ported, unwired, WIP branch pushed; `Astroray-batchH` worktree kept on it.
- Interim + final RTX sweeps: 806 passed / 0 failed (see STATUS for xfail/xpass counts).

## Dispatch order (lead's recommendation, batched)

Batch K — **volumes part 2** (Opus 4.8, cite-algorithm): pkg270 emission + blackbody spectral Planck +
  per-λ σ (spectral/decomposition tracking, Kutz 2017), then pkg269 GPU wavefront stage (NanoVDB device grid,
  `template<bool>` fleet isolation, REG 254 probe) — one lane, CPU first; #807 cabinet as the cross-check.
Batch L — **lighting residuals**: #814 (FIRST fix the dedicated-sun direction vs Cycles — pixel-measure a pole's shadow vector in both renders; THEN re-measure gate 2 with the ROI drawn on both images; analytic E_sun oracle for the disc; controlled single-spot IES A/B vs
  `kernel/light/spot.h`; wavefront IES modulation), Preetham/Hosek sky types → Nishita-or-warn decision,
  world_sky_sky corpus refs re-rendered with the Nishita sky.
Batch M — **viewport storm row**: reduce the coalesced-commit cost (pkg266 follow-up, #721), re-measure §9 storm.
Batch N — **parity fill**: #767 (three distinguishing tests), #763 four-way variance table, run_parity
  `textured_emitter` + `sky_sun` with an addon-driven leg (#779 option b), pkg242 Phase 2 real-Blender parity,
  pkg254 remaining xfails (cryptomatte buffer format, HDR/gamma round-trip), pkg245 architect review.
Then: pkg265 Phase 3 GPU walk (multi-build lane from the WIP STATE doc), pkg271 volume passes + corpus family.

## Per-batch flow

One worktree per batch → implement each item with its own tests → build + focused pytest → `/lint` →
PR → CI → CUDA build under the GPU lock → GPU tests + saved render → you inspect the render →
`cpp-abi-guard` / `cycles-parity-reviewer` / `pr-reviewer` where headers/physics/behaviour changed →
call-site sweep → squash-merge (verify) → spec Status flip → STATUS.md line.

## Closeout (last ~90 minutes)

Merge or park with a state-of-play comment; flip spec statuses; STATUS.md top block; regenerate
`KNOWN_ISSUES.md` (`python scripts/dev/known_issues_report.py`); rebuild the index + graph; `lint --all`
clean; consolidate memory; rebuild main `build_cuda` + restage/install the addon from main; final RTX
sweep; run report (`.claude/skills/run-report`, template + `scratchpad/lead/build_report.py` pattern);
write the morning message and the next handoff prompt in this format.
