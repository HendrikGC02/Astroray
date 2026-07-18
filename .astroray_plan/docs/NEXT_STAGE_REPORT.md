# Astroray Next Stage Report

**Date:** 2026-07-18 (First travel-laptop session — pkg114 closeout)
**Prepared by:** Claude (Anthropic Code) — updated after the 2026-07-18 round (pkg114 exporter integration landed → pkg114 fully COMPLETE; portability + research + cleanup direct-to-main; first session on the RTX 3000 Ada travel laptop).
**Scope:** post-2026-07-18 next stage. **The active arc is pkg55 Phase C** (§2 item 1 — MIS audit + megakernel removal + 2× perf gate; **Session C1 already in flight**).

> ⚠️ **UPDATE 2026-07-18 (first travel-laptop session):** New machine — **RTX 3000 Ada (sm_89), CUDA 13.2, no OptiX SDK, no OpenEXR**. Fresh clean full build succeeds; full suite **1285 passed / 0 failed / 32 skipped / 19 xfailed / 4 xpassed** in 9m11s (the 32 skips are OptiX-SDK + OpenEXR-gated tests the workstation full-featured build unlocks — NOT a regression). **pkg114 is now fully COMPLETE** (PR #479 — exporter `Change.TRANSFORMS` → inc-3d TLAS-only refit; headless Blender 5.1 refit byte-identical to full re-sync, mad 0.00000). Direct-to-main: CUDA-13 `bin\x64` DLL-layout portability + laptop-portable hooks/skills; dead-root-file cleanup; the 2026-07 PBR-advances research sweep (+ follow-up pass); `total_max_depth` cap gate promoted xfail→live; the pkg55 Phase C implementation plan. **pkg55 Phase C Session C1 is in flight** on `feat/pkg55-c1-spectral-tables-extraction`.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> 2026-07-18 round is authoritative for the current state).

---

## 1. Current state (one screen)

- **pkg114 COMPLETE this round (2026-07-18).** The last follow-up — the exporter transform-only dispatch → TLAS-only refit — landed (PR #479, pure Python; the C++/CUDA bindings were in #468). The addon exporter's `Change.TRANSFORMS` viewport path now takes the inc-3d fast path (re-walk `depsgraph.object_instances`, `update_instance_transform` per dupli, `upload_instance_transforms`, `render(skip_upload=True)`) for a pure-transform GPU batch whose changed objects are all instanced sources or eligible instancer empties; everything else falls back to full sync. Headless Blender 5.1 refit is byte-identical to a full re-sync (mad 0.00000). **Every pkg114 acceptance criterion AND its follow-ups are now closed.**
- **First session on the travel laptop:** RTX 3000 Ada (sm_89), CUDA 13.2, **no OptiX SDK, no OpenEXR**. CUDA-13 relocated the Windows CUDA DLLs to `bin\x64`; runtime + addon bundler + hooks now probe both layouts (direct-to-main 74e9bd1).
- **Fresh clean CUDA-13.2 build sweep: 1285 passed / 0 failed / 32 skipped / 19 xfailed / 4 xpassed** in 9m11s. The 32 skips are OptiX-SDK + OpenEXR-gated (not a regression on this machine). `total_max_depth` cap gate is now a live test (promoted xfail→live, dd670b7).
- **2026-07 PBR-advances research landed (docs-only, direct-to-main):** `.astroray_plan/docs/2026-07-pbr-advances-research.md` + `-pass2.md`. Verified, license-clean adoption candidates now exist for post-Phase-C material/transport work (see §2). RTXDI is DISQUALIFIED (proprietary) for any ReSTIR-PT path — use the paper + author reference code.
- **Blender 5.1 is installed on this machine.** Agents CAN re-bless cross-engine Cycles references (PR #410 precedent).
- **pkg55 Phase C Session C1 in flight** (`feat/pkg55-c1-spectral-tables-extraction`). The Phase C plan (`.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md`, 7 sessions C1–C7, delete-megakernels-last) is authoritative.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg55 Phase C (active) → pkg115/pkg89 small follow-ups → pkg88 C.1 + Phase B → pkg64 spectral caustics → post-Phase-C material candidates. Pillar 4 (pkg45/46/48/49/50/51 + pkg107) ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. **pkg114 is DONE** (closed this round — the exporter integration was its last follow-up). CI is **Linux/CPU only** — pick CPU work whose correctness can be gated without a GPU; GPU-gated items must be RTX-verified at closeout.

**Top priority (autonomous, GPU-gated — do on RTX):**

1. **pkg55 Phase C — megakernel removal + MIS audit + 2× gate** (GPU, large ~3 weeks; **Session C1 IN FLIGHT**). The active arc. Follow the plan doc `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` — 7 sessions C1–C7, **delete the megakernels LAST**. C1 (in flight) extracts the shared spectral-tables layer + light-tree probe out of `multiwavelength_kernel.cu` (the C1 blocker). Verified state going in: light-tree NEE is already in the wavefront; TLAS/motion/non-visible-band/photon-caustics are NOT (those are named Phase-C deferrals). Phase C demonstrates ≥ 2× end-to-end speedup on the Disney contact-sheet (7 material types, 1024 SPP) vs the Phase-A megakernel baseline, ports the power-heuristic MIS weighting, and migrates ReSTIR reservoirs to GPU SoA if needed; all pkg54/54a/54b SSIM gates must pass with the megakernel deleted. Cite **GRIS** (Lin et al. 2022, DOI 10.1145/3528223.3530158) for the ReSTIR-to-wavefront reservoir design.
2. **pkg115 small follow-ups** (GPU visual verify, small). Gradient + noise spheres near-black on the addon path (evaluator/translation bugs); pkg89 dedicated-light energy-scale audit (GPU leg dark = dedicated lights not uploaded; CPU exposure uniformly dimmer than Cycles at equal wattage); per-object texture instancing for shared materials. Recorded in the pkg115 spec.
3. **pkg88 C.1 — per-primitive motion blur split** (perf-gated B/C4 decision per spec). Phase C.0 DONE (PR #437); C.1 is the Cycles `prim_time` early-out split, taken only if a measured regression vs Cycles justifies the complexity. **Phase B** (addon motion bake) — the pkg114 inc-3c/3d addon area it waited on is now stable, so this is unblocked. **Phase D** (wavefront SoA integration) — after pkg55 Phase C.
4. **pkg64 — spectral caustics** (huge, ~3–4 wk). The SMS CPU spectral caustic path.

**Post-Phase-C material / transport candidates (from the 2026-07 PBR-advances research — file as packages once Phase C stabilizes the wavefront as the only pipeline):**

5. **Specular Polynomials — Newton-free SMS seed-finding** (moderate-high). Fan et al., SIGGRAPH 2024, DOI 10.1145/3658132, arXiv:2405.13409. Reformulates specular constraints as univariate root-finding; kills SMS's bad-seed divergence and one-solution-per-seed failure. The highest-value **bounded** upgrade to our existing SMS (pkg64/pkg106 lineage). Ref impl `github.com/mollnn/spoly` ("MIT-style" — VERIFY license before porting).
6. **Thin-film iridescence (Belcour-Barla, via OpenPBR)** (moderate). Self-contained, showcase-friendly BSDF layer. OpenPBR spec is Apache-2.0 with a MaterialX reference; its recommended thin-film model is **Belcour-Barla**. NOTE the verified refutation: OpenPBR's slab-layering is NOT a multiscatter blueprint — port it only for thin-film/coat/fuzz.
7. **Turquin multiscatter-LUT reflection energy compensation** (moderate). Port **Turquin-style albedo-scaling LUTs** using `adobe/openpbr-bsdf` (**Apache-2.0**, 7 CUDA-ready multiscatter energy LUTs) as the primary reference and post-#107958 Cycles (`cycles_precompute.cpp`) as the cross-check. Verified: Cycles removed its stochastic multiscatter GGX for exactly this. Complements pkg118 — that fixed *transmission* energy; this is *reflection* multiscatter at high roughness. Composes with our existing LUT infra (heed the pkg118 lesson: energy bugs hide in albedo-LUT paths).

**Horizon (watch, do not port yet):** SVO-based wavefront path guiding (the architectural match to our wavefront kernel — VERIFY repo availability), Partitioned-SMS+ReSTIR (needs Phase-C reservoirs first), Manifold Path Guiding, 3D-Gaussian photon guiding, ReSTIR-PG.

**GPU-gated pool:**

8. **SPPM-progressive + VCM** (owner decision). GPU-gated; CI has no GPU.

**Pillar 4 (PAUSED per owner directive 2026-06-08):**

- **pkg45/46/48/49/50/51 + pkg107** — all ON PAUSE until core rendering is
  working/stable/sufficiently progressed. **Do NOT pick up Pillar-4 specs.**

**Note on test suite:** The full local suite on the laptop build has **ZERO failures** (1285 passed / 0 failed / 32 skipped / 19 xfailed / 4 xpassed). The 32 skips are OptiX-SDK + OpenEXR-gated (this laptop has neither). **Do NOT bulk-promote the 4 xpassed gates** — dd670b7 shows `filter_glossy` / caustics-flag gates xfail on this laptop despite June workstation xpasses (machine/precision-dependent); `total_max_depth` was the one safely promotable this round.

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, full local test + stale-call-site sweep before each push, poll CI then
`gh pr merge --squash --delete-branch`.** **Continue pkg55 Phase C** (§2 item 1 — Session C1 is in flight on `feat/pkg55-c1-spectral-tables-extraction`; follow the plan doc `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md`, delete-megakernels-last, ≥2× gate on the Disney contact-sheet 1024spp vs the Phase-A baseline, cite GRIS for the ReSTIR-to-wavefront reservoir design). If Phase C is blocked, take pkg115/pkg89 follow-ups (§2 item 2) or pkg88 C.1/Phase B (§2 item 3). Cite papers per CLAUDE.md §6 for any new algorithm (`/cite-algorithm`) — the post-Phase-C material candidates (§2 items 5–7) already have their research records saved; **re-verify each reference repo's license against the actual repo before writing code** (the research docs flag several as VERIFY). The round is GPU-heavy; clean CI-only CPU wins are exhausted.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI (pr-reviewer
  doc-only rule). Source PRs need the independent-review SIGN-OFF/BLOCK gate (pkg98)
  before push.
- **CI is blind to GPU correctness** — a green CI is necessary but not sufficient for
  any glass/caustic/GR render change. Do not declare a round clean on CI green alone;
  run the full RTX hardware sweep at closeout (memory: `ci_has_no_gpu_runtime_blindspot`).
- **This machine is the travel laptop (RTX 3000 Ada, CUDA 13.2, no OptiX SDK, no OpenEXR).** 32 tests skip here that pass on the workstation full-featured build (OptiX-SDK + OpenEXR-gated) — this is expected, not a regression. CUDA 13 relocated the Windows CUDA DLLs to `bin\x64`; the runtime/addon bundler/hooks probe both layouts.
- **Visual check is mandatory for caustic/dispersion/rough-glass renders** — both
  `hue_spread` and `bright_coverage` can pass on dense chromatic salt-and-pepper noise,
  and rough glass looks see-through at low spp (MC noise, not a bug). Eyeball the PNG
  (memory: `general-photon-loop-needs-solid-glass`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** — this report's
  §2 prose can go stale vs STATUS.md; the spec header is authoritative for done/open
  (memory: `orchestrator-next-stage-report-stale`).
- **xpassed gates are machine-dependent — do NOT bulk-promote.** `total_max_depth` was safely promoted this round (7/7 stable on the laptop, XPASSing on the workstation since June); `filter_glossy` / caustics-flag / direct-indirect-clamp gates xfail on this laptop despite June workstation xpasses — leave them xfail.
- **RTXDI is DISQUALIFIED (proprietary)** for any ReSTIR-PT/GRIS work — use the paper + author reference code, or reimplement. Re-verify every candidate reference repo's license against the actual repo before porting (the 2026-07 research docs flag several as VERIFY).

---

## 5. After the round

- Flip any landed spec `Status:` lines to `done (PR #N, date — headline numbers)`.
- Update STATUS.md (new round section + the next pickup queue), ROADMAP.md (round-closeout
  entry + pillar long-tail), and rewrite this report's §1/§2 for the next round.
- Run the RTX hardware sweep; re-confirm all merged PRs hold on hardware (caustics, glass,
  motion blur, light tree, etc.). Record the full test-suite state (passed/failed/skipped/
  xfailed/xpassed counts) and the machine (workstation vs travel laptop — the skip count differs).
- Promote xpassed gates to live tests ONLY where stable on the running machine (they are machine/precision-dependent).
- Open ONE doc PR for the closeout; it is doc-only and auto-merge eligible.
