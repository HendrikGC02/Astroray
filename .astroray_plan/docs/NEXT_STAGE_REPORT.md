# Astroray Next Stage Report

**Date:** 2026-06-11 evening (Round closeout — pkg55-B' Sessions N+7 parts 3-7 COMPLETE — wavefront 1.45-1.52× @ 1.5× threshold)
**Prepared by:** Claude (Anthropic Code) — rewritten at the 2026-06-11 evening round closeout (8 PRs: pkg55-B' Sessions N+7 parts 3-7 autonomous).
**Scope:** post-2026-06-11-evening next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> Round 15 Wave 6 section is authoritative for the current state).

> ⚠️ **UPDATE 2026-06-11 evening:** **pkg55-B' Phase-B performance goal MET** (all RTX-verified; final sweep on merged main 99ffc7a: 1272 passed / 0 failed / 23 skipped / 18 xfailed / 6 xpassed).
> **pkg55-B' Sessions N+7 parts 3-7 DONE** (PRs #450-#457, 2026-06-11 — wavefront program went 4.0×-slower → 1.45-1.52×-FASTER than megakernel today: Part 3 intersect/shade split + material-bucketed shade (correctness-clean; honest no-win-yet; diagnosed per-sample round structure as bottleneck); Part 4 PATH REGENERATION (Laine §4) — wavefront BEAT megakernel first time: 1.34× @ depth 8, 1.40× @ depth 16/512spp, depth trend reversed; pkg98 SIGN-OFF with hand-traced exactly-once accumulation. Perf-gate scene (disney_contact_sheet, balanced 7-material 4×2 grid) + two-tier gate (hard floor ≥1.15×, 1.5× xfail target). Shadow-stage factoring blueprint (A/B/C split of sampleDirectSpectralMW). Shadow stage — sampleDirectSpectralMW factored into gpu_nee_sample/occlude/resolve (megakernel recomposes byte-identically); wavefront defers trace to dedicated shadow kernel; perf-neutral 1.39×, honest occupancy-not-binding finding. Knob re-prioritization — shared-NEE insight: curand_init elimination is relative-gate lever. Template-RNG materials/NEE — gpu_materials.h's 15 samplers + gpu_nee_sample templated over RNG type (megakernel codegen unchanged); wavefront draws direct PCG — 1.39× → 1.46× stable; perf floor raised 1.15 → 1.30; convention amendment to spec §4.2 #2 documented. Any-hit shadow traversal (gpu_bvh_occluded / gpu_tlas_occluded; PBRT IntersectP / Cycles scene_intersect_shadow) — ratio 1.45-1.52×, AT 1.5× threshold; 1.5× target XPASSED in cool full-suite run (1272/0, 6 xpassed); thermal-throttling caveat documented; cool-GPU re-baseline is named follow-up. All 22 wavefront gates pass; full suite 1272/0. pkg98 SIGN-OFF (Opus) all parts. REMAINING for B' close: cool-GPU perf re-baseline (1.5× xfail likely flips), wavefront_path_tracer plugin registration, pkg81 viewport-parity gate; reviewer-noted any-hit adoption candidates (stage_light_sample legacy TODO, path_trace_kernel RGB NEE) are small follow-ups).
>
> **6 xpassed gates** (the 1.5× perf target + 5 others: total_max_depth caps, filter_glossy, reflective-caustics flags, 2 spectral ones from earlier rounds) — promote candidates next round. **Expected suite state:** 0 failures / 18 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others; down from 20 after xfail → xpass promotions). pkg114 inc3 (addon instancing) still pending with dedicated agent.
>
> The next autonomous lead pool is **pkg55 Phase B completion** (cool-GPU perf re-baseline + wavefront_path_tracer plugin registration + pkg81 viewport-parity gate) → **pkg115 dedup + RTX visual verify** → **pkg88 C.1** (perf-gated per-primitive split) + **Phase B** (addon bake, after pkg114 inc3) → **pkg64** (spectral caustics, huge). All GPU-gated + RTX-verifiable.
>
> **Owner directives (2026-06-08):** (1) **Pillar 4 (pkg45/46/48/49/50/51 + pkg107) is ON
> PAUSE** until the rest is working/stable/sufficiently progressed — do not pick it up.
> (2) The broken old-Blender benchmark scenes (Classroom/BMW27/Junkshop/UDIM_monster) were
> **removed**; **pkg76 Classroom/BMW27/Junkshop fidelity is dropped** from the pool.
> cornell is the only remaining Cycles-parity scene.

---

## 1. Current state (one screen)

- **pkg55-B' Phase-B performance goal MET this round (2026-06-11 evening).** Sessions N+7 parts 3-7 DONE (PRs #450-#457 — wavefront went 4.0×-slower → 1.45-1.52×-FASTER than megakernel today): Part 3 intersect/shade split + material-bucketed shade (correctness-clean; diagnosed per-sample round structure as bottleneck). Part 4 PATH REGENERATION (Laine §4) — wavefront BEAT megakernel first time: 1.34× @ depth 8, 1.40× @ depth 16/512spp; pkg98 SIGN-OFF with hand-traced exactly-once accumulation. Perf-gate infrastructure (disney_contact_sheet.py + two-tier gate: hard floor ≥1.15×, 1.5× xfail target). Shadow-stage factoring blueprint + implementation — sampleDirectSpectralMW factored into gpu_nee_sample/occlude/resolve; megakernel recomposes byte-identically; wavefront defers trace to dedicated shadow kernel; perf-neutral 1.39×, occupancy-not-binding finding. Knob re-prioritization — curand_init elimination is relative-gate lever. Template-RNG materials/NEE — gpu_materials.h 15 samplers + gpu_nee_sample templated; wavefront draws direct PCG — 1.39× → 1.46× stable; perf floor raised 1.15 → 1.30. Any-hit shadow traversal (gpu_bvh_occluded / gpu_tlas_occluded) — ratio 1.45-1.52×, AT 1.5× threshold; 1.5× target XPASSED in cool full-suite run (1272/0, 6 xpassed); cool-GPU re-baseline is named follow-up. All 22 wavefront gates pass; full suite 1272/0. pkg98 SIGN-OFF (Opus) all parts. REMAINING for B' close: cool-GPU perf re-baseline, wavefront_path_tracer plugin registration, pkg81 viewport-parity gate.
- **RTX sweep on merged main 99ffc7a: 1272 passed / 0 failed / 23 skipped / 18 xfailed / 6 xpassed.** The 6 xpassed gates include the 1.5× perf target (xpassed on cool full-suite run — worth listing for next-round promotion alongside others). **Expected suite state:** 0 failures / 18 xfails (down from 20; legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others). pkg114 inc3 (addon instancing) still pending with dedicated agent.
- **Blender 5.1 is installed on this machine.** Agents CAN now re-bless cross-engine Cycles references (PR #410 proves it).
- **No open PRs.** The PR queue is empty.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg55 Phase B completion (cool-GPU perf re-baseline + plugin registration + pkg81 viewport-parity gate) → pkg115 dedup + RTX visual verify → pkg88 C.1 + Phase B (after pkg114 inc3) → pkg64 (spectral caustics). Pillar 4 (pkg45/46/48/49/50/51 + pkg107) ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. **pkg55-B' Sessions N+7 parts 3-7 are DONE** (closed this round — wavefront 1.45-1.52× @ 1.5× threshold). CI is **Linux/CPU only** — pick CPU work whose correctness can be gated without a GPU.

**Top priority (autonomous, GPU-gated — do on RTX):**

1. **pkg55 Phase B completion — cool-GPU perf re-baseline + plugin registration + viewport-parity gate** (GPU, small). Cool-GPU perf re-baseline (single fresh-boot run — 1.5× xfail likely flips to pass). `wavefront_path_tracer` plugin registration. pkg81 viewport-parity gate (the pkg81-measured CUDA 104 ms vs CPU 58 ms blocker — megakernel register pressure, now addressed by the wavefront). Deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch. Reviewer-noted any-hit adoption candidates (stage_light_sample legacy TODO, path_trace_kernel RGB NEE) are small follow-ups. **Sessions N+7 parts 3-7 DONE** (PRs #450-#457, 2026-06-11 — wavefront 1.45-1.52× @ 1.5× threshold).
2. **pkg115 dedup + RTX visual verify** (GPU visual verify, small). Addon-side private texture-definition duplication removal (Approach step 4) + Blender-vs-Cycles paired-still RTX visual (`/verify`). **Chunks 1-5 DONE** (PRs #439/#441/#442/#445/#446 — Noise/Wave/Brick/Voronoi Cycles parity complete).
3. **pkg88 C.1 — per-primitive motion blur split** (perf-gated B/C4 decision per spec). Phase C.0 DONE (PR #437); C.1 is the Cycles `prim_time` early-out split only if measured regression vs Cycles justifies the complexity. **Phase B** (addon bake) — start after pkg114 inc3 merges (same addon area). **Phase D** (wavefront SoA integration) — after pkg55-B.
4. **pkg64 — spectral caustics** (huge, ~3–4 wk). The SMS CPU spectral caustic path.

**GPU-gated pool (previously OWNER-BLOCKED, now autonomous after this round's merges):**

5. **pkg55-B' CUDA sessions** (wavefront port continuation after Phase B — per-material
   shade kernels). Multi-session GPU-gated work.
6. **SPPM-progressive + VCM** (owner decision). GPU-gated; CI has no GPU.

**Pillar 4 (PAUSED per owner directive 2026-06-08):**

- **pkg45/46/48/49/50/51 + pkg107** — all ON PAUSE until core rendering is
  working/stable/sufficiently progressed. **Do NOT pick up Pillar-4 specs.**

**Note on test suite:** The full local test suite has **ZERO failures** (expected suite
state: 0 failures / 18 xfails, down from 20). The 6 xpassed gates (1.5× perf target +
total_max_depth caps, filter_glossy, reflective-caustics flags, 2 spectral from earlier)
now PASS — promote candidates to live tests next round. The 18 xfails are legacy pkg64-gpu
SMS gates + pkg86 2× variance gates + others. The previous pkg64-gpu parity SSIM xfail
(item 6 in the prior report) is RESOLVED (xfail'd as legacy per
`pkg64-gpu-hw-sweep-2026-05-31.md` RESOLUTION section).

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, full local test + stale-call-site sweep before each push, poll CI then
`gh pr merge --squash --delete-branch`.** **Start with pkg55 Phase B completion** (§2 item 1 — cool-GPU perf re-baseline: single fresh-boot run, 1.5× xfail likely flips to pass; wavefront_path_tracer plugin registration; pkg81 viewport-parity gate) or **pkg115 dedup + RTX visual verify** (§2 item 2 — addon-side texture duplication removal + Blender-vs-Cycles paired-still RTX visual). Both are GPU-gated + RTX-verifiable. Cite papers per CLAUDE.md §6 for any new algorithm (`/cite-algorithm`). The next round is GPU-heavy; clean CI-only CPU wins are exhausted.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI (pr-reviewer
  doc-only rule). Source PRs need the independent-review SIGN-OFF/BLOCK gate (pkg98)
  before push.
- **CI is blind to GPU correctness** — a green CI is necessary but not sufficient for
  any glass/caustic/GR render change. Do not declare a round clean on CI green alone;
  run the full RTX hardware sweep at closeout (memory: `ci_has_no_gpu_runtime_blindspot`).
- **Visual check is mandatory for caustic/dispersion/rough-glass renders** — both
  `hue_spread` and `bright_coverage` can pass on dense chromatic salt-and-pepper noise,
  and rough glass looks see-through at low spp (MC noise, not a bug). Eyeball the PNG
  (memory: `general-photon-loop-needs-solid-glass`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** — this report's
  §2 prose can go stale vs STATUS.md; the spec header is authoritative for done/open
  (memory: `orchestrator-next-stage-report-stale`).
- **Blender 5.1 is installed on this machine** — agents can re-bless cross-engine Cycles
  references (PR #410 proves it). No longer an "owner Blender re-render" blocker for
  pkg104-family cross-engine work.
- **Promote the 6 xpassed gates next round** — 1.5× perf target (xpassed on cool full-suite
  run), `total_max_depth` caps, `filter_glossy`, reflective-caustics flags (spectral
  path_tracer ported them), 2 spectral from earlier rounds now PASS; remove xfail decorators
  and move to live tests.

---

## 5. After the round

- Flip any landed spec `Status:` lines to `done (PR #N, date — headline numbers)`.
- Update STATUS.md (new round section + the next pickup queue), ROADMAP.md (pillar
  status + long-tail), and rewrite this report's §1/§2 for the next round.
- Run the RTX hardware sweep; re-confirm all merged PRs hold on hardware (caustics, glass,
  motion blur, light tree, etc.). Record the full test-suite state (passed/failed/skipped/
  xfailed/xpassed counts).
- Promote the 3 xpassed gates to live tests if they still pass.
- Open ONE doc PR for the closeout; it is doc-only and auto-merge eligible.
