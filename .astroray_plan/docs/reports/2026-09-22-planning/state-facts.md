# Astroray Pillar-4 exit-gate state sheet — 2026-09-22

Read-only fact sheet. Every number cites file/command. UNMEASURED = no artifact found.
Budget used: ~20 tool calls (index queries, doc reads, gh, git, file probes).

---

## 1. Exit gate table (gate rows from `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` §2)

| Row | Target | Last measured | Status | Still needed |
|---|---|---|---|---|
| **(a) Viewport responsiveness** | GPU p95≤100ms/p99≤150ms present latency; cancel-ack p95≤200/p99≤300ms; denoise out of interactive loop | In-process harness only (`benchmarks/viewport_parity/2026-09-03.json`): camera-only 10k-tri p50 34.7/p99 37.7ms; w/ OIDN-in-loop p50 140.8/p99 184.8ms (already >100ms). Real-Blender numbers since: pkg241 Phase1a addon-only A/B metal_sweep material p95 964→155ms, big 1495→224ms, big-camera p95 169→64ms (PASSES ≤100ms budget on that one config; source: pkg241 spec status via `project_index.py whatis pkg241`). Post-#850 full re-sync floor ~125ms/edit (issue #855 title, still open, unmeasured artifact). Orbit tick gap p95 76.9ms vs 44.6ms sync (issue #854, open). | **AMBER** | pkg241/pkg266 gate never closed to a single real-Blender p95/p99 table across BOTH pinned scenes; #855/#854/#857 (worker ignores render border) all open and unresolved. No single canonical "gate (a) PASS" artifact exists. |
| **(b) Shader-socket coverage** | ≥95% frequency-weighted coverage over ~50-scene corpus, zero silent drops in corpus scenes (raw DROPPED-SILENT count is diagnostic only per owner 2026-09-07 §7) | `docs/blender_parity/coverage_matrix.json` regenerated 2026-09-20 12:49 (586 rows); `docs/blender_parity/report.md` (mtime 2026-09-11, but counts match the 586-row matrix exactly — treat as current): **SUPPORTED 122 / APPROXIMATED 61 / DROPPED-SILENT 403 = 68.8%** of 586. This is WORSE in raw % than the 2026-09-07 reaudit (340/527=64.5%) because pkg260 added +59 rows (object/image-property/input-node), but raw count is explicitly not the gate metric. **No frequency-weighted score has ever been computed** — report.md has no "weighted" section (grepped, 0 hits besides unrelated TEX_GABOR "Frequency" socket name). | **UNMEASURED** (gate metric itself never run) | Someone must run the frequency-weighted scorer against the pkg259 corpus (9 `.blend` families now exist under `benchmarks/reference_corpus/scenes/`) — this scorer script/step is not evidenced anywhere found. pkg253 (Principled advanced) DONE, pkg255 (Metallic) DONE, pkg256 (Sky, #799 part1) partial, pkg257 (Displacement) DONE — the 4 named nodes are no longer all DROPPED-SILENT, but no re-score exists to prove ≥95%. |
| **(c) Three reference scenes, CPU+GPU, parity-clean** | Exactly 3 pinned `.blend` (cornell interior, material zoo, HDRI+hair), F12 both backends, ±5% ROI ratio + SSIM≥0.95 + non-vacuity | Placeholder problem from 2026-09-07 is resolved: `benchmarks/blender_parity/scenes/cornell_interior.blend` exists (real, not the old placeholder); `blender_addon/scenes/metal_sweep.blend` exists. `ir_vegetation.blend`/`uv_skin.blend` (the HDRI+hair candidates) only found under `test_results/rebuild-handoff-20260906/{cpu,cuda}-addon/scenes/` — i.e. copied test-run artifacts, not an authored/pinned asset in a source scenes dir; unclear if still byte-identical placeholders (2026-09-07 note) or real. pkg259 corpus (done, 5 families, PRs #761/#781/#785/#806) is a SEPARATE, larger 9-scene corpus (`geometry_zoo`, `camera_lens`, `lighting_studio`, `materials_hall`, `render_settings`, `textures_mapping`, `volumes_smoke`, `world_sky_hdri`, `world_sky_sky`) that owner 2026-09-08 morning said gate (c) **switches to once built** — it is now built. | **AMBER** — assets exist but no consolidated 3-scene (or corpus-trio) parity run/report was found in this pass | Confirm whether gate (c) now runs against the pkg259 corpus (per owner 2026-09-08 decision) rather than the original 3 named files; locate/produce the actual CPU+GPU parity numbers for whichever set is authoritative. `benchmarks/cycles-parity/` latest dated files are 2026-09-20 (`README.md`, `ies_spot/`) — raw per-scene ±5%/SSIM table not read in this pass (budget). |
| **(d) Adaptive sampling + denoise from native panels** | Output-effect test (AOV differs, noise falls) both CPU+GPU, driven only from native panel props | Landed both backends (pkg131, #659 CPU/#665 GPU, HW-verified) — from north-star doc §2(d), unchanged since 2026-09-07. GPU denoise wired (pkg197). Per `landed-features-off-by-default-audit` memory (2026-09-08), GPU adaptive was reported inert in Blender at that time (#759) but #759 is in KNOWN_ISSUES.md's "Recently closed" list (closed 2026-09-09) — so the addon-level reachability bug is fixed. A single "one smoke test, native-panel→engine, both backends" (the exact gate instrument) was **not located** in this pass. | **AMBER** | Locate/author the single combined smoke test the gate spec asks for; confirm it's green post-#759 fix. |
| **(e) Zero open high-severity addon-bug** | 0 open `addon-bug` issues at P0/P1 | Label now exists (`gh label list`: `addon-bug` = "Blender addon defect: wrong image, crash, or native setting silently ignored"; `addon-gap` also exists) — 2026-09-07's "label doesn't exist" blocker is resolved. `KNOWN_ISSUES.md` (generated 2026-09-20 02:50, stale by ~2 days) states **open addon-bug at P0/P1 = 1** (#721, viewport 155ms/1.3Hz). Current `gh issue list --state open` (this session, 2026-09-22) confirms **#721 still open, still labeled addon-bug + P1-high**; no other open issue carries both `addon-bug` and a P0/P1 label (checked all 33 open issues' label sets). | **RED** (target 0, actual 1) | Close or re-triage #721 (viewport responsiveness — same root issue feeding gate (a)). |
| **(f) Documented one-command build+install, clean machine** | Fresh-profile install via Blender's extension installer, one F12, no toolchain | `scripts/dev_addon.ps1` + `scripts/build/build_blender_addon.py` exist; `dist/astroray-4.0.0-cuda.zip` ships; transactional installer placed 42 files, passed isolated smoke (`rebuild-handoff-2026-09-06.md`). Issue #769 (zip missing `data/disney_compensation/*.bin`, addon-bug P1-high) is in KNOWN_ISSUES.md's "Recently closed" (closed 2026-09-08) — the P1 blocker named in owner's 2026-09-08 evening decision ("fix next session as P1") is fixed. No new clean-machine (no-toolchain, fresh profile) verification artifact found this pass. | **AMBER**, partially GREEN per 2026-09-07 language (developer loop is one-command; true clean-machine end-user verification still unconfirmed) | A literal fresh-profile/no-toolchain install+F12 run, with evidence saved. |

---

## 2. Open issues (33 total, `gh issue list --state open --limit 60`, 2026-09-22) grouped

### Blocks a gate row directly
- **#721** P1-high, addon-bug, performance — viewport camera-event block ~155ms, refine idles 1.3Hz. **Blocks (a) and (e).**
- **#859** bug, lighting, P1-high — GPU loses sun with mesh emitter present (0.22→0.027). Correctness, not gate-labeled but P1.
- **#857** addon-bug — viewport worker ignores render border (#802 regression). Blocks (a)/(f)-adjacent addon quality.
- **#854** addon-bug, performance — orbit tick gap p95 76.9 vs 44.6ms sync. Blocks (a).
- **#855** performance — storm re-sync ~125ms/edit floor. Blocks (a).
- **#856** performance — orbit chroma noise re-measure (PR #843 follow-up). Blocks (a).
- **#858** addon-gap — owner try-out checklist for viewport worker default. Gate (a) precondition (no default flip until done).
- **#846** material, addon-bug — GPU op-VM drops procedural-input programs on Roughness/Metallic/IOR/Transmission silently. Blocks (b) (silent-drop requirement).
- **#823** material — parity scanner blind to `_compile_socket_value` (op-VM Math/Mix/Map Range reads misreported DROPPED-SILENT). Blocks (b) measurement validity itself.
- **#822** material — op-VM coordinate-side non-affine math unsupported (pkg277 spec open). Blocks (b).
- **#845** cycles-parity, addon-bug — orthographic/panoramic cameras render as perspective. Blocks (c)/(f) correctness.
- **#833** cycles-parity, addon-bug — mesh+volume material renders as bounding-box (icosphere→cube). Blocks (c) volumes scene.
- **#773** cycles-parity, performance, P2-medium, addon-bug — addon render path loses ~15% at rough-glass limb vs in-process engine. Blocks (c) parity.

### Science-foundational (spectral/instrument/band, qualifies per §3 of north-star doc)
- **#848** P3-low — pkg206 hero-λ logistic refit to CIE 1931 2° ȳ post-#767.
- (No open issues directly tagged pkg243/pkg133/pkg130/pkg251 found in the open list — those packages' issue-tracking may live only in specs, not GH issues.)

### Pillar-4-adjacent (frozen, not to pick up)
- **#144** — spectral nebula emission/reflection media (Pillar 4 volume/GR-adjacent, P1-high label but frozen by north-star §1.1).
- **#141** — diffraction grating / spectral mirror BSDF (P1-high label, but science/Pillar-4-flavored, not gate-critical).
- **#398** — engine-agnostic core / USD-Hydra delegate (architecture, long-horizon, not gated).

### Hygiene / correctness debt not gate-blocking today
- **#862** P2-medium — CPU↔GPU red divergence 11.4%→9.1% on session_n1_envmap_cornell (post-#863 metric fix; residual tracked, gate now bounds absolute gap not exact match).
- **#861** — test writes overwrite tracked PNGs under test_results/batchF (test hygiene).
- **#860** cycles-parity, volume — mesh-bounded volumes render 0.75-0.81× Cycles (grid volumes match within 2%).
- **#853** P2-medium — GPU principled_hair ~11% brighter unpigmented, darker-in-blue pigmented (pkg225 GPU leg).
- **#852** cycles-parity — area light spread<180° ~6× dark vs Cycles.
- **#851** cycles-parity, P2-medium — CPU light tree 8-14× noisier than power sampler (owns #763).
- **#849** enhancement, performance — in-place material/light/transform viewport updates (avoid full re-sync).
- **#847** cycles-parity — Generated coordinates wrong for rotated objects (world-AABB texspace frame).
- **#842** cycles-parity, volume — ray segment only sees nearest volume's bounds; others skipped.
- **#832** enhancement — env-map lookup texel-edge vs Cycles texel-center half-texel offset.
- **#789** enhancement — rough-glass MS walk achromatic (no dispersion, pkg265 follow-up).
- **#783** enhancement — thin-film-aware MS microfacet glass walk (pkg265 follow-up).
- **#763** cycles-parity, performance, P2-medium — corpus CPU noisier than Cycles CPU at equal spp (owned by #851 root cause).
- **#39, #38, #36** P3-low — persistent-data animation, tiled rendering, holdout/indirect-only (old backlog, low priority).

---

## 3. Landed-since-2026-09-07 features that materially moved the gate

(PR list from `gh pr list --state merged --limit 30`, cross-referenced against project-index `whatis`; not exhaustive back to 09-07 — only the most recent ~20 shown by the query, session boundary 2026-09-19→20 confirmed.)

- **#830 (pkg274)** — addon gaps: native Cycles device-when-auto (#722), missing-texture DEGRADED+magenta warn (#723), camera clip planes (#724), holdout alpha hole (#36).
- **#829 (pkg275)** — HDRI reflection lookup gap fix.
- **#824 (batch-L)** — sun direction fix + irradiance re-measure, IES spot, Preetham/Hosek sky.
- **#820 (batch-K, pkg269/pkg270)** — GPU heterogeneous volume stage + volume emission/spectral Planck/per-λ σ.
- **#819 (batch-M, #817)** — viewport worker present-while-orbiting + full-res refinement.
- **#831** — material-only depsgraph edits take incremental replay not full re-sync (#721 storm row).
- **#836** — MinGW GCC 15.2 NanoVDB build fix (#827).
- **#837 (batch-T)** — #767 colour skew, #763 variance table, #779 addon parity leg.
- **#838 (batch-Q)** — #828 GPU blackbody + grid cache, pkg271 volume passes/AOVs/corpus, #833 reported (not yet fixed).
- **#839 (batch-P)** — pkg276 IES×spot + GPU IES, #840 lamp radius, #841 light shader, #834 Generated coords.
- **#843 (batch-S)** — native Principled emission on wavefront (#835), Cycles navigation samples for orbit preview.
- **#844 (batch-R)** — #825 texIdx key, #826 multi-input GPU programs, #822 design + pkg277 spec filed.
- **#850** — viewport material/light/geometry edits re-sync (stale replay since #831).
- **#863** — observer fallout fix across 6 GPU gates (pkg64 pins re-captured, HDRI dark-channel rule, pkg55 absolute-gap metric) — this closed out gate-adjacent regressions from the CIE 1931 2° observer switch (#837).
- Gate-(b)-relevant node packages, all **done** per project index: **pkg253** (Principled advanced), **pkg255** (Metallic BSDF), **pkg257** (Displacement), **pkg256** (Sky texture, #799 part 1 only — Nishita Phase 2 still tracked separately).
- **pkg259** (Cycles feature-coverage reference corpus) — **done**, all 5 scene families landed (#761/#781/#785/#806), directly closes the gate-(c) asset-existence blocker.
- **pkg260** (coverage-scanner extension) — **done** (#758), added object/image-property/input-node rows (527→586).
- **pkg241** — **done** per spec status (Phases 0–2.2 delivered #733/#739/#748/#750/#768/#777); P2.3 residual moved to pkg266.
- **pkg258** (HDRI env NEE/importance sampling) — **done** both CPU+GPU (#747/#751).

## 4. Recent throughput (last 4 sessions, from STATUS.md/handoff docs)

- **2026-09-19→20 session** (per `next-session-prompt-2026-09-21.md`): **8 PRs merged** — #836 #850 #843 #844 #839 #837 #838 #863. Final RTX sweep: **899 passed / 0 failed / 8 skipped / 9 xfailed / 1 xpassed**, 6:30 runtime. Two usage-limit kills during the session (lanes resumed via raw agentId). opencode/deepseek spend: **US$0.049** (deepseek-v4.1-flash critic passes, $0.003–0.007 each).
- **2026-09-19 session** (from PR list, e.g. #830/#829/#824/#820/#819/#821/#817-fix): high-volume batched-lane day, ~10+ PRs, exact session boundary/count not separately isolated in this pass (would need `STATUS.md` CURRENT block, not reached — budget).
- Earlier sessions (2026-09-13 batchH/batchF/batchK/batchJ etc.) — **not itemized this pass**; STATUS.md CURRENT block (top) was not read (only tail/history was fetched by accident via `tail -300`; recommend re-reading the top of STATUS.md for the actual 2026-09-20 CURRENT block, which is the authoritative recent-session record — **this is a gap in this deliverable**, flagged below).
- RTX sweep pass counts beyond the 899/0/8/9/1 figure above: **not independently found** for earlier sessions in this pass.

## 5. In-flight worktrees / branches

- `git worktree list`:
  - `C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray` @ `604b03f0` [main]
  - `C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-batchH` @ `862596ee` [feat/batch-h2-pkg265-gpu-walk] — pkg265 Phase 3 GPU walk, **untouched since 2026-09-13** per `next-session-prompt-2026-09-21.md`; WIP-STATE doc `pkg265-phase3-gpu-walk-WIP-STATE.md`.
- `git branch -r | head -40` shows a large number of stale `origin/codex/*`, `origin/arch/*`, `origin/claude/*`, `origin/chore/*` branches from as far back as pkg124/pkg138 work — none confirmed merged-and-deletable in this pass; full remote-branch audit not done (budget).
- Open specs still live (from next-session-prompt): **pkg277** (coordinate-side op-VM warp, #822), **pkg272** (volume motion blur/multiscatter, optional), **pkg273** (cloud volume material, PAUSED horizon item).
- No open PRs as of the 2026-09-20 handoff ("Main 9f586d75 + docs... No open PRs"). Current HEAD per git status snapshot is `604b03f0` (2026-09-22 policy commit), so at least one more commit landed since that handoff without a fresh next-session doc describing it — **STATUS.md CURRENT block for 2026-09-20/21/22 not read in this pass; gap**.

## 6. Known process pain points (from STATUS/handoff docs)

- **Usage-limit kills mid-session**: 2 kills in the 2026-09-19→20 session; lanes had to be resumed via raw agentId (memory: `continuing-agents-without-sendmessage`, `usage-limit-kills-agents-commit-wip-early`).
- **CI has no GPU**: closeout sweep is the first place GPU-gated tests run; this session's sweep caught 6 failures, all from the observer/CIE-2°-switch change, fixed as metrics not engine touches (`ci_has_no_gpu_runtime_blindspot`).
- **Builds/tests/CI are "the biggest time waster"** (owner 2026-09-11) → batched-lanes directive: several independent items per worktree/build/sweep/CI cycle, one PR per batch.
- **Lead-runs-builds-lanes-never-poll**: four lanes polling queued CUDA builds previously killed the usage window twice (memory `lead-runs-builds-lanes-never-poll`); current protocol has the lead background every CUDA build and resume lanes when `.pyd` is ready.
- **Colour-baseline invalidation**: CIE 1931 2° observer switch (#837, 2026-09-20) invalidates any colour baseline pinned before that date — "attribute against a build, do not re-baseline blind."
- **Viewport gate measured on the wrong instrument** (north-star §6 risk 1): the 37.7ms p99 in-process number bypasses the real Blender GPU blit; still not fully superseded by a real-Blender number covering both pinned scenes (see gate (a) row above).

---

## Gaps / what is missing (explicit, per instructions)

1. **STATUS.md top ("2026-09-20 CURRENT block") was not read** — the `tail -300` command returned older history (Round 15, 2026-05-xx era) because STATUS.md's newest entries are apparently not at the literal file tail in the expected place, or the file is huge and tail undershot. This is the single biggest gap: §4 throughput and the true current-session state should be re-pulled from the top/most-recent section of STATUS.md directly.
2. **`.astroray_plan/docs/reports/2026-09-20-lead-session.html`** was not fetched/extracted in this pass (budget).
3. **`.astroray_plan/docs/blender-coverage-reaudit-2026-09.md`** was not re-read in full (only referenced via project-index search hit); frequency-weighted methodology detail may live there.
4. **NEXT_STAGE_REPORT.md** (694 lines) was not read in this pass — may contain additional gate-relevant sequencing not captured above.
5. **Full remote-branch and CI-run audit** not performed — `git branch -r` truncated to first 40 (~150+ branches likely exist), no merged/stale classification done.
6. **`benchmarks/cycles-parity/` latest per-scene ±5%/SSIM numbers** (2026-09-20 `ies_spot/`, `README.md`) not extracted — only directory listing was checked.
7. **Whether `ir_vegetation.blend`/`uv_skin.blend` are still byte-identical placeholders** was not verified (found only under a test-results copy, not a canonical source scenes directory) — needs a `sha256sum`/`git log` check.
