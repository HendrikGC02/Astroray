# Next-session prompt — 2026-09-20 handoff

Paste everything below the line into a fresh Claude Code (Fable 5.1) session opened in the main
checkout. Written by the outgoing lead (2026-09-15 18:30 → 2026-09-19 evening AEST; four usage-limit
kills and one OAuth expiry, every lane resumed from its transcript). Owner decisions it cites are in
`north-star-and-integration-gate-2026-09-07.md` §7 and STATUS.md.

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside
Blender 5.2. Continue feature development and repo improvement in the same manner as the previous
lead sessions, autonomously, for a long unattended stretch. **Batched lanes** (owner 2026-09-11):
several independent items per worktree / build / sweep / CI cycle, one PR per batch with per-item
sections and tests.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` (north star, gate (a)–(f), §7).
3. `.astroray_plan/docs/STATUS.md` top block (2026-09-19 CURRENT).
4. The run report `.astroray_plan/docs/reports/2026-09-19-lead-session.html`.
5. `.astroray_plan/docs/issue-audit-2026-09-15.md` (decisions + the owner's `gh` block — check which
   closes the owner has run with `gh issue list --state open`).
6. Specs: **pkg276** (IES × spot composition + GPU wavefront IES), **pkg271** (volume passes + corpus
   family + Blender integration), pkg272 (optional), **pkg273** (cloud-volume material — PAUSED horizon
   item, do not dispatch), pkg265 Phase 3 (`pkg265-phase3-gpu-walk-WIP-STATE.md`, worktree
   `Astroray-batchH`); issues #828 #822 #823 #825 #826 #827 #832 #721 #767 #763 #779 #773.
7. Memory (read first): `no-fable-agents` (BANNED again 2026-09-19), `lead-runs-builds-lanes-never-poll`,
   `continuing-agents-without-sendmessage` (after a lead restart resume by raw agentId),
   `auto-mode-classifier-blocks-issue-close-and-profile-install`, `deepseek-v41-flash-4x-grunt`,
   `delegate-tier-stalls-on-hard-packages` (2026-09-19 update: what deepseek-v4-pro is good at),
   `roi-mean-over-specular-highlight-artefact`, `viewport-gate-table-misses-real-navigation`.

## Hard constraints (owner directives — do not reinterpret)

- **Models.** NO Fable subagents (owner 2026-09-19). Opus 4.8 lanes = `package-implementer` /
  `cpp-abi-guard` / `cycles-parity-reviewer` / `pr-reviewer` / `architect` with the `model` parameter
  OMITTED; `model: "sonnet"` only for Sonnet 5 lanes. **Lean on opencode** (owner 2026-09-15): grunt =
  `opencode-go/deepseek-v4.1-flash` (4× limits for a limited time — re-check), implement =
  `opencode-go/deepseek-v4-pro` for bounded, tightly-specified addon/Python/small-header work (the lead
  builds and verifies), critic = deepseek-v4.1-flash with the diff INLINED in the prompt. glm-5.3-flash
  times out on multi-command sweeps. Codex credits return 2026-09-20 — one cheap call is the only test.
- **Usage limits kill lanes.** At most 2–3 Claude lanes at once; the LEAD runs every CUDA build in the
  background (`gpu_locked_build.py … *> build_cuda\lead_build.log`, zero tokens while waiting) and
  resumes the lane when the `.pyd` is ready. Lane briefs carry the TOKEN DISCIPLINE block (one
  10-minute-timeout call, log file + grep, no short polling). Keep every lane's raw agentId in a
  scratchpad note; commit + push after every step.
- **Blender.** 9876 = owner's live instance — never touch. Measurement/GUI lanes:
  `scripts/dev/launch_isolated_blender.ps1 -Port 9877 -Worker 0|1 -StateDir <dir> -StagedAddon
  <worktree>\dist\astroray` (scratch `BLENDER_USER_EXTENSIONS`; also stages the `mcp` bridge). Headless
  A/Bs use the same scratch-extensions trick and assert the loaded addon path. NEVER `--install` from a
  lane; only the lead's closeout restage of MAIN installs.
- **GPU.** One CUDA build / GPU run at a time under `.astroray_plan/.orchestrator.gpu.lock` (MAIN
  path): builds via `scripts/build/gpu_locked_build.py`, anything else via
  `scripts/build/gpu_locked_run.py <who> -- <cmd>` (always the MAIN checkout's copy). `.pyd` mtime vs
  HEAD before any GPU number; canary `hasattr`.
- **GitHub writes.** The lead's `gh issue close/comment` is blocked by the permission mode; put
  `Closes #N` in PR bodies and leave an owner `gh` block in a docs file. `gh pr create/merge` work.
- **Worktrees / line endings / specs / merging:** unchanged from the 2026-09-14 handoff (sibling
  worktrees, remove only after MERGED + clean; `__init__.py` mixed CRLF/LF; STATUS + specs CRLF via
  bytes; TEMPLATE v2 + `project_index.py lint`; PR + CI green + GPU gate + your own render inspection
  + `cpp-abi-guard` / `cycles-parity-reviewer` where headers / physics changed → `gh pr merge --squash`).
- **Evidence.** Like-for-like contact sheets through the ADDON path for anything the owner sees in
  Blender (a direct engine render is not evidence for an addon bug); per-pixel median + ratio map for
  glossy ROIs; Cycles clamps off for parity renders; draw every ROI on a PNG and look.

## State you inherit (verified 2026-09-19 evening)

- Merged this session: **#819 #820 #821 #824 #829 #830 #831**; no open PRs. Specs done: pkg269, pkg270,
  pkg274, pkg275. Filed: pkg273 (paused), pkg276 (open), issues #822 #823 #825 #826 #827 #828 #832.
- **Volumes**: per-λ extinction + Principled Volume emission + spectral Planck (CPU); GPU wavefront
  heterogeneous stage (NanoVDB device grid, ≤ 8 media, grids re-uploaded per render, constant emission
  only — blackbody is CPU-only and reported as a degradation, #828). #807 resolved.
- **Sky**: dedicated Nishita sun direction matches Cycles through the addon path; irradiance within
  ~5 % (the 1.48× number was invalid). Preetham/Hosek route to Nishita with a warning. IES × spot → pkg276.
- **Shader graph**: procedural textures are op-VM inputs (GPU bakes 64² / 64³); multi-input programs
  warn on GPU (#826); coordinate-side non-affine math open (#822); scanner blind spot (#823); the
  Generated-coordinate checker on a plane renders slightly smaller / phase-shifted cells than Cycles on
  BOTH backends (seen in `test_results/batchN/issue818_contact_sheet.png`, no issue yet).
- **Viewport**: worker (opt-in) presents while orbiting and refines at full res; material storms use
  the incremental replay (#831). Still open before re-proposing the default: metal_sweep orbit row
  (76.9 ms vs 44.6 ms OFF), ~80 ms render/present tick gap in storms, 1-spp spectral chroma noise in
  the orbit preview, and Principled Emission Strength 0→5 not visibly lighting the GPU viewport
  (pre-existing, same ON and OFF — file it).
- **HDRI**: lookup + spectral upsample byte-faithful on CPU and GPU (probe tests); #755 not
  reproducible; #795 was a highlight-mean artefact; residual +11 % green skew vs Cycles on chrome
  (fold into #767).
- **Addon / .pyd**: main `build_cuda` rebuilt and the addon restaged `--backend cuda` + installed at
  closeout (see STATUS for the build id and the sweep numbers). `--backend cpu` staging is broken
  under MinGW GCC 15.2 since #810 (#827).
- Worktrees: main + `Astroray-batchH` (pkg265 Phase 3 WIP, untouched this session).

## Dispatch order (lead's recommendation, batched)

Batch P — **lighting / shading residuals** (Opus 4.8 + cite-algorithm): pkg276 IES × spot + GPU IES;
  the Generated-coordinate checker mismatch (file the issue first, with the #821 sheet); #832 only if
  it rides along for free.
Batch Q — **volumes part 3**: pkg271 passes + corpus family + Blender integration; #828 GPU blackbody
  emission + device-side grid cache (REG probe first); a showcase VDB render for the README (the
  pkg269 evidence is a tiny dark puff).
Batch R — **op-VM coverage**: #822 coordinates as VM inputs (REG 254 risk — probe with cuobjdump
  before writing the feature), #826 multi-input programs on GPU, #825 texIdx key = pointer + mapping
  bits, #823 scanner + corpus proof cards (deepseek-v4-pro candidate for the scanner half).
Batch S — **viewport**: metal_sweep orbit regression, storm tick gap (render/present), emission-strength
  viewport bug, then a real-navigation owner try-out before any default flip.
Batch T — **parity fill** (unchanged from the last handoff): #767 three distinguishing tests (+ the
  chrome green skew), #763 four-way variance table, #779 option b, pkg242 Phase 2, pkg254 remaining
  xfails, pkg245 architect review, #773 (pkg264 owner).
Build hygiene (deepseek-v4-pro candidate): #827 MinGW NanoVDB `--backend cpu` staging.
Then: pkg265 Phase 3 GPU walk (multi-build lane from the WIP STATE doc).

## Per-batch flow and closeout

Unchanged from the 2026-09-14 handoff, plus: the lead runs the builds; a staged-addon restage comes
BEFORE the closeout sweep (the Blender-facing tests in `pytest -m gpu` run against `dist/astroray`, and
a stale staged `.pyd` fails them with `setup_camera(): incompatible function arguments`).
