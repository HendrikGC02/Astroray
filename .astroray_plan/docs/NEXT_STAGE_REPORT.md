# Astroray Next Stage Report

**Date:** 2026-07-20 (Overnight travel-laptop round — pkg55 Phase C C3+C4 closeout)
**Prepared by:** Claude (Anthropic Code) — updated after the 2026-07-19 → 2026-07-20 round (pkg55 Phase C Sessions C3+C4 landed, C5 open-verified; pkg89 GPU dedicated lights + energy audit; pkg121-A chi² harness; pkg119-A parity coverage matrix; 15 specs filed pkg123-137).
**Scope:** post-2026-07-20 next stage. **The active arc is still pkg55 Phase C** — 5 of 7 sessions done/verified; **Session C6 (ReSTIR SoA) is the next pickup**, then C7 (2× gate + megakernel deletion) closes the arc.

> ⚠️ **UPDATE 2026-07-25 ~mid-run (architect adjudications — amends the 2026-07-24 banner below; spec `**Status:**` headers remain the dispatch source of truth):** (1) **PR #518 (pkg141) ADJUDICATED MERGEABLE** on its own green gates (near-delta parity 2.7–4.0× → 0.60–0.77 in-band, 7/7 `--runxfail`); the HW FAIL is fully attributed to pre-existing main-branch wavefront_diff/perf failures now owned by **pkg153** (gate-failure-reviewer feeding it); the 4 xfail rows are removed IN the PR (carry-over checklist in the pkg141 spec); residual GPU dimness → **pkg152** (not tonight). (2) **PR #519 (pkg151) ADJUDICATED MERGEABLE STANDALONE as groundwork** — but its stack premise is **FALSIFIED** (compensation ceiling ~1.03× vs required 1.2–11×; furnace unchanged 0.11–0.82 under the corrected sampler): **Lane A is REWRITTEN to pkg151 → pkg154 (furnace root-cause investigation, measurement phase overnight-safe) → pkg149 (stays HELD behind pkg154) → pkg150 (canceled for tonight)**. (3) **Interim HW protocol** until pkg153 is dispositioned: re-run failing gates on unmodified main @ pinned SHA; PR-attributable failures block, main-attributable log to pkg153 — adjudicate PRs on their own gates.
>
> ⚠️ **UPDATE 2026-07-24 (architect boot pass for overnight run #2 — supersedes ALL banners and §1/§2 prose below where they disagree; spec `**Status:**` headers remain the dispatch source of truth):** Since the 2026-07-23 banner: **pkg145/pkg146/pkg144/pkg138 shipped** (#513/#514/#515/#517), **pkg148 shipped** (#516 merged 2026-07-24 — the `get_integrator()` hold is resolved), **pkg149 root-caused and HELD** (corrected `sampleGgxVNDF` at `670e583` on worktree `Astroray-pkg149`, unpushed — KEEP that worktree), specs pkg147/148/149/150/151 filed. Full detail: `.astroray_plan/docs/standup/2026-07-23-overnight.md`. **Tonight's dispatch set (2026-07-24 → morning), explicit PARALLEL lanes — owner wants maximum safe parallelism; `disney.cpp` stays single-writer:**
>
> - **Lane A (serial, owns `plugins/materials/disney.cpp`): pkg151 → pkg149 → pkg150.** pkg151 (rough-transmission multiscatter compensation; Cycles glass-table symbols CONFIRMED 2026-07-24 — `.astroray_plan/docs/pkg151-cycles-glass-tables-research.md`, implementation-ready), then pkg149 (rebase/stack `670e583`, one PR chain, furnace [0.92,1.03] + peak-alignment <2° green together; chi² glass[0.3-45] un-xfail only with BOTH green, `--runxfail`-verified). pkg150 is CONDITIONAL slot 3 (only after the chain merges + HW-passes with ≥2 h left; first action = re-baseline). One implementer owns the whole lane.
> - **Lane B (parallel): pkg141** GPU near-delta Disney metal brightness (diagnostic-first S1/S2 adjudication; un-xfails the pkg123 near-delta parity rows). Must not touch `disney.cpp`; soft file overlap with Lane A only in `include/astroray/gpu_materials.h` (metal vs dielectric regions) — **serialize merges, rebase second-lander**.
> - **Lane C (parallel): pkg147** addon CPU render hang — re-assessed overnight-SAFE with guardrails (all Blender calls subprocess + hard timeout; OpenMP-`.pyd` check first; ~3 h time-box; see spec). Fully disjoint files (`blender_addon/`, build flags).
> - **Serialization constraints for the team-lead:** (1) `disney.cpp` = Lane A only; **pkg124 explicitly NOT tonight** (it promotes the very `sampleGgxVNDF` helper pkg149 fixes — see its spec note); pkg128/pkg129 also touch `disney.cpp` — not tonight. (2) One RTX hardware-verifier at a time across ALL lanes (memory `cuda_verifier_concurrency`); doc-only PRs skip GPU verify. (3) Never rebase/push a branch mid-HW-run (`hw-verify-branch-freeze`). (4) `Astroray-pkg149` worktree must survive the night until `670e583` is on a pushed branch. (5) If a lane stalls and a slot frees: prefer finishing other lanes over starting new packages; pkg121-B (chi² gallery) is tempting but would be invalidated by Lane A's sampler change — do NOT run it tonight. pkg126 is UNBLOCKED (pkg122 done) but is an L-effort day-arc — not tonight.
>
> ⚠️ **UPDATE 2026-07-23 (architect boot pass for the overnight run — supersedes §1/§2 prose below where they disagree; spec `**Status:**` headers remain the dispatch source of truth):** Since the 2026-07-20 report: **pkg55-C6 CLOSED** (#497 C6a + #503 C6b ReSTIR reuse merged — Phase C is 6/7; only **C7** — 2× gate + megakernel deletion — remains, deliberately NOT queued for unattended runs), **pkg123 done** (#498, chi² 163→0), **pkg122 done** (#500 — gross energy factors eliminated; branch fully squash-merged, worktree kept as pkg146 oracle evidence), **pkg139/pkg140 done** (#505/#507), **pkg142 ADJUDICATED** (keep `RGBIlluminant` D65, #511 reverted, residual offset → **pkg146**), **pkg143 superseded by pkg145**, **pkg125 done** (#499). **Tonight's ordered dispatch set (2026-07-23): pkg145 → pkg146 → pkg144 → pkg138** (pkg141 as alternate); rationale + research pointers in each spec. pkg145/pkg138/pkg124 all edit `disney.cpp` — **serialize their merges** (pkg145 first). New research: `.astroray_plan/docs/pkg145-diffuse-specular-coupling-research.md` (Cycles `closure_layering_weight` / OpenPBR glossy-diffuse albedo scaling).

> ⚠️ **UPDATE 2026-07-20 (overnight travel-laptop round):** Machine is the **RTX 3000 Ada (sm_89), CUDA 13.2, no OptiX SDK, no OpenEXR** travel laptop. **pkg55 Phase C advanced C3→C5:** C3 (PR #486, non-visible-band + naive-MW wavefront, agreement-on-black gates) and C4 (PR #490, TLAS/instancing + deformation motion) landed; **C5 (PR #494, photon caustics) MERGED post-closeout (confirmed 2026-07-20)** — Phase C is 5/7 sessions merged. **pkg89 GAP-1** (PR #489) uploaded dedicated lights to the GPU (Blender-lamp scenes no longer render DARK on GPU; AREA 0.998 / POINT 0.997 parity); **GAP-2 energy audit** escalated the CPU wattage→radiance mis-scaling to **pkg122** (spec PR #488). **pkg121 Phase A** (PR #485) landed the Mitsuba 3 chi² harness (Lambertian passes p=0.23; Disney spec-lobe → pkg123). **pkg119-A** (PR #487) landed the first Blender parity coverage matrix (131 SUPPORTED / 23 APPROXIMATED / 370 DROPPED-SILENT / 20 stale sockets of 524). **15 specs filed (pkg123-137).**

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> 2026-07-19 → 2026-07-20 round is authoritative for the current state).

---

## 1. Current state (one screen)

- **pkg55 Phase C is 5 of 7 sessions done/verified.** C1 (spectral-tables extraction, #481), C2 (MIS audit — no bug found, #484), C3 (non-visible-band + naive-MW wavefront, #486), C4 (TLAS/instancing + deformation motion, #490), and **C5 (photon caustics, #494 — merged post-closeout, confirmed 2026-07-20)** are merged (2/2 C5 gates + 40-test regression green on RTX). Remaining: **C6 (ReSTIR reservoir SoA, GRIS-anchored)** and **C7 (2× end-to-end gate, then delete the megakernels LAST)**. Plan doc `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` is authoritative.
- **Notable Phase-C findings for the record:** the GPU wavefront was **never run-to-run bit-exact** (parallel atomic accumulation, architectural ~2e-7 floor — C4 gate adjudicated to the 1e-5 Monte-Carlo convention); the C3 "573× NIR divergence" was a **stale shadow `.pyd` + a never-compiled forward decl**, not an emission bug (root-shadow-pyd trap now killed direct-to-main, 94ae956); the prior "MW megakernel black in NIR" claim is **RETRACTED** (real gap = CPU `path_tracer` band-unawareness → pkg125); dedicated lights are **still absent from wavefront NEE** (pkg89 follow-up, in C6/C7 scope — it is why the C5 gate scene's non-caustic component renders black).
- **pkg89 dedicated lights now reach the GPU (GAP-1, #489)** but their **energy is mis-calibrated (GAP-2)** — AREA 0.13× / point ~3.6× opposite / blackbody ~14× vs Cycles at equal wattage; not a clean factor, escalated to **pkg122** (spec PR #488, `.astroray_plan/docs/pkg89-energy-audit-2026-07.md`). This is the user-visible dimness.
- **pkg121 chi² harness (Phase A, #485) is live** and already found real defects: the **Disney specular lobe fails sample()/pdf() statistically** (xfail'd, residual maps localize the defect at the lobe core) → **pkg123**. Phase B (validation campaign + publication-quality gallery) is spec'd; the first gallery is already rendered at `test_results/chi2_visuals_2026-07/`.
- **pkg119-A parity coverage matrix (#487) is the first honest measurement** of addon vs Blender feature coverage (131/23/370, 20 stale-socket latent addon bugs of 524 sockets). Phases B (differential harness + the stale-socket fixes) + C are open.
- **15 new specs filed (pkg123-137)** — correctness/sampling, material candidates, and eight platform techniques from the 2026-07 engine sweeps. All have research records; **re-verify each reference repo's license against the actual repo before writing code** (several are flagged VERIFY).
- **Blender 5.1 is installed on this machine.** Agents CAN re-bless cross-engine Cycles references (PR #410 precedent).
- **Hardware is moving back to the RTX 5070 Ti workstation imminently.** Wipe + fresh-configure the OneDrive `build_cuda` on arrival (the cross-machine stale-build trap, `DEVELOPMENT.md`); laptop-pinned observations (the seed-flaky direct/indirect-clamp gate, walltime baselines) may differ there.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg55 Phase C C6→C7 (active) → pkg123 Disney spec-lobe adjudication → pkg122 energy calibration → pkg119-B + stale-socket fixes → pkg121-B visual campaign. Pillar 4 (pkg45/46/48/49/50/51 + pkg107) ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. CI is **Linux/CPU only** — GPU-gated items must be RTX-verified at closeout.

**Tonight's set (2026-07-23, ordered — weighted toward VISIBLE render improvements for the morning before/after report):**

1. **pkg145 — Disney specular energy refit + diffuse-under-specular coupling** (heads the standup queue; the 2026-07-21 decomposition finding is in the spec). Fix = Cycles `closure_layering_weight` / OpenPBR glossy-diffuse albedo scaling — research note `.astroray_plan/docs/pkg145-diffuse-specular-coupling-research.md`, in-repo `table_ggx_E` supplies E, no new table. Restores the 15-config quarantined grid to 1.02. **Visible:** grazing-angle Disney materials (sphere-grid + furnace before/after renders).
2. **pkg146 — equal-wattage offset investigation** (measure-first; pkg122 1.07–1.16× vs pkg139 0.96–1.01× oracle contradiction). Produces live-Cycles A/B renders for the report; likely closes the "brighter/dimmer than Cycles" complaint. No risky code — investigation contract forbids blind fixes.
3. **pkg144 — firefly clamp direct/indirect split** (port Cycles `film_clamp_light` into the already-stubbed `clampDirect`/`clampIndirect`; remove the always-on `sLum>20` cap that silently biases delta-light NEE). Un-xfails the 2 highlight tests from #498 (memory: xfail-gated features must un-xfail). **Visible:** bright-sun scenes stop asymptoting at ~14–20 luminance.
4. **pkg138 — Disney dielectric rough-reflection eval** (UNBLOCKED by #498; delta-vs-continuous sample/pdf mismatch, chi² 143M at glass[0.3-45]). **Visible:** rough-glass highlight/MIS correctness. **Serialize after pkg145** (both edit `disney.cpp`).

**Alternate (if a slot frees):** pkg141 GPU near-delta Disney metal brightness (unblocked, RTX render gates). **Deliberately NOT tonight:** pkg55-C7 (megakernel deletion — too destructive for an unattended run), Pillar 4 (paused), pkg127-137 platform ports (post-C7).

**Prior-round list (2026-07-20, kept for context — statuses below are stale where the banner above disagrees):**

1. **pkg55 Phase C — Session C6 (ReSTIR reservoir SoA), then C7 (2× gate + megakernel deletion)** (GPU, large; **C6 is the next pickup, the arc's finale is C7**). Follow the plan doc `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md`. **C6** builds a flat double-buffered reservoir SoA + temporal/spatial reuse as wavefront stages + `restir_di` GPU dispatch; gate = `test_restir_validation.py::TestTemporalVariance::test_temporal_reduces_variance` passes with `restir-di` on the GPU wavefront + the DI bias tests hold; it may split C6a (SoA + initial RIS + resolve) / C6b (temporal + spatial reuse). **Cite GRIS** (Lin et al. 2022, DOI 10.1145/3528223.3530158) for the reservoir design; **RTXDI is DISQUALIFIED (proprietary)** — use the paper + our CPU ReSTIR-DI code; `github.com/DQLin/ReSTIR_PT` is **license-VERIFIED BSD-3-Clause (2026-07-20, cleared for mirroring with attribution — `.astroray_plan/docs/restir-pt-license-verification.md`)**. **C7** confirms every gate is green on a wavefront-only run, turns on the ≥2× end-to-end gate (Disney contact sheet, 7 materials, 1024 spp, vs the pinned Phase-A megakernel baseline), repoints `render()`/`renderMultiwavelength()` at the wavefront, then **deletes both megakernels LAST** with a repo-wide stale-call-site sweep. **Bringing dedicated lights into wavefront NEE (pkg89 follow-up) belongs here** — it is why the C5 gate scene renders black off the caustic. Measure the 2× ratio on a cool GPU (the ratio is the robust metric; absolute times drift under thermal load).
2. **pkg123 — Disney specular-lobe chi² adjudication** (CPU-gated, CI-friendly; the merged pkg121 xfails point straight at it). Un-xfail the pkg121 Disney gates by fixing the sample()/pdf() mismatch; the residual maps already localize the defect at the lobe core. Likely overlaps **pkg124 (VNDF sampling for the Disney specular reflection lobe)** — the canonical fix for NDF-vs-VNDF pdf mismatch. Highest-value CI-gatable correctness win in the queue.
3. **pkg122 — dedicated-light energy calibration** (CPU-gated; **blocked-clear now that pkg89 GAP-1 landed**). Fixes the user-visible dimness: AREA 0.13× / point ~3.6× opposite / blackbody ~14× vs Cycles at equal wattage. Not a clean factor — needs the per-type calibration the audit doc (`pkg89-energy-audit-2026-07.md`) scopes. GPU==CPU parity already holds, so a CPU fix propagates.
4. **pkg119-B — differential parity harness + the stale-socket addon fixes** (CPU/addon-gated, CI-friendly). Phase A found 20 stale-socket latent addon bugs + the DROPPED-SILENT long tail; Phase B builds the differential harness and lands the concrete addon fixes.
5. **pkg121-B — chi² validation campaign + visual gallery** (CPU-gated; owner loves the graphs). The comprehensive per-lobe campaign + publication-quality HTML gallery; the first gallery is already rendered. Best paired with pkg123 (adjudicate → then show the residual maps going green).
6. **pkg125 — CPU `path_tracer` band awareness** (CPU-gated, CI-friendly, small). Honor `set_wavelength_range` on the CPU path_tracer (or reject it loudly) — the retracted-claim finding from C3.

**Post-Phase-C material / transport candidates (specs now filed — pick up once Phase C stabilizes the wavefront as the only pipeline):**

7. **pkg127 Specular Polynomials** (Newton-free SMS seed finding; the highest-value bounded upgrade to our SMS lineage — verify `github.com/mollnn/spoly` license), **pkg128 thin-film iridescence** (Belcour-Barla via OpenPBR, Apache-2.0), **pkg129 Turquin reflection multiscatter LUTs** (`adobe/openpbr-bsdf`, Apache-2.0 — complements pkg118's transmission fix).
8. **pkg126 mesh-emitter unification** (pkg89 Phase C — one sampling interface for dedicated + emissive-geometry lights; natural follow-on once wavefront NEE has dedicated lights from C6/C7).

**Horizon (specs filed, do not port yet):** pkg136 SVO wavefront path guiding (the architectural match to our wavefront kernel — needs C7 done first), pkg137 partitioned SMS+ReSTIR caustics (needs Phase-C reservoirs), pkg130-135 platform techniques (light groups, adaptive sampling, host-mapped spill, SRF sensors, LPEs, demand-loaded textures).

**Pillar 4 (PAUSED per owner directive 2026-06-08):**

- **pkg45/46/48/49/50/51 + pkg107** — all ON PAUSE until core rendering is
  working/stable/sufficiently progressed. **Do NOT pick up Pillar-4 specs.**

**Note on test suite:** The full local suite on the laptop build had **ZERO failures** last full sweep (1285 passed / 0 failed / 32 skipped / 19 xfailed / 4 xpassed; the 32 skips are OptiX-SDK + OpenEXR-gated — this laptop has neither). **Do NOT bulk-promote the xpassed gates** — `filter_glossy` / caustics-flag / direct-indirect-clamp gates xfail on this laptop despite June workstation xpasses (machine/precision-dependent). Re-run the full sweep on the workstation after the hardware move — the skip count and the xpass set will differ.

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, full local test + stale-call-site sweep before each push, poll CI then
`gh pr merge --squash --delete-branch`.** **Continue pkg55 Phase C — Session C6** (§2 item 1: ReSTIR reservoir SoA + reuse stages on the GPU wavefront; may split C6a/C6b; cite GRIS; DQLin/ReSTIR_PT license verified BSD-3-Clause 2026-07-20, cleared for mirroring; the CPU ReSTIR-DI code is the primary generator regardless). **Then C7** closes the arc (≥2× gate on the Disney contact sheet 1024spp vs the Phase-A baseline, repoint `render()`, delete both megakernels LAST with a full stale-call-site sweep, bring dedicated lights into wavefront NEE). If Phase C is blocked, take the CI-gatable correctness wins: **pkg123** Disney spec-lobe adjudication (+ pkg124 VNDF), **pkg122** energy calibration, **pkg119-B** stale-socket fixes, **pkg125** CPU band awareness. Cite papers per CLAUDE.md §6 for any new algorithm (`/cite-algorithm`); the post-Phase-C material candidates (pkg127-129) have research records saved — **re-verify each reference repo's license against the actual repo before writing code** (several are flagged VERIFY).

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI (pr-reviewer
  doc-only rule). Source PRs need the independent-review SIGN-OFF/BLOCK gate (pkg98)
  before push.
- **CI is blind to GPU correctness** — a green CI is necessary but not sufficient for
  any glass/caustic/GR/ReSTIR/wavefront change. Do not declare a round clean on CI green alone;
  run the full RTX hardware sweep at closeout (memory: `ci_has_no_gpu_runtime_blindspot`).
- **The GPU wavefront is NOT run-to-run bit-exact** (parallel atomic accumulation, ~2e-7 floor — C4/#490). Gate wavefront correctness at the 1e-5 Monte-Carlo convention, NOT exact equality; a miswritten exact-equality gate will flake or falsely fail.
- **Watch the shadow-`.pyd` trap** — a stale worktree-root `.pyd` shadowing `build_cuda/Release/` produced C3's phantom 573× "divergence". The trap is killed direct-to-main (94ae956: `sys.path` reorder + blocking hook), but verify `astroray.__file__` resolves to the canonical `build_cuda/Release/` path before trusting any GPU number, and check `.pyd` mtime vs HEAD (memory: `stale_pyd_locations`).
- **Hardware is moving back to the RTX 5070 Ti workstation.** On arrival, **wipe + fresh-configure the OneDrive `build_cuda`** (the cross-machine stale-build trap — OneDrive syncs a stale build between machines; `DEVELOPMENT.md`). The workstation full-featured build (OptiX SDK + OpenEXR) unlocks 32 tests the laptop skips; laptop-pinned observations (seed-flaky clamp gate, walltime baselines) may differ there.
- **Visual check is mandatory for caustic/dispersion/rough-glass renders** — both
  `hue_spread` and `bright_coverage` can pass on dense chromatic salt-and-pepper noise,
  and rough glass looks see-through at low spp (MC noise, not a bug). Eyeball the PNG
  (memory: `general-photon-loop-needs-solid-glass`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** — this report's
  §2 prose can go stale vs STATUS.md; the spec header is authoritative for done/open
  (memory: `orchestrator-next-stage-report-stale`).
- **RTXDI is DISQUALIFIED (proprietary)** for any ReSTIR-PT/GRIS work — use the paper + author reference code, or reimplement. Re-verify every candidate reference repo's license against the actual repo before porting (the 2026-07 research docs flag several as VERIFY).
- **Keep plan-doc formats compatible with `Google_Apps_Script.txt`** — it drives the owner's Sheets tracker (owner directive this round; the `dist/` tcnn zip is kept, the pkg119 corpus runner was cut).

---

## 5. After the round

- Flip any landed spec `Status:` lines to `done (PR #N, date — headline numbers)`. If pkg55-C5 (#494) merged, mark it done in the Phase-C plan doc; otherwise leave it open-verified.
- Update STATUS.md (new round section + the next pickup queue), ROADMAP.md (round-closeout
  entry + pillar long-tail), and rewrite this report's §1/§2 for the next round.
- Run the RTX hardware sweep; re-confirm all merged PRs hold on hardware (dedicated lights, caustics, glass,
  motion blur, TLAS/instancing, ReSTIR, etc.). Record the full test-suite state (passed/failed/skipped/
  xfailed/xpassed counts) and the machine (workstation vs travel laptop — the skip count differs).
- Promote xpassed gates to live tests ONLY where stable on the running machine (they are machine/precision-dependent).
- Open ONE doc PR for the closeout; it is doc-only and auto-merge eligible.
