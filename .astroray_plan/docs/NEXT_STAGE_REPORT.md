# Astroray Next Stage Report

**Date:** 2026-06-11 (Round closeout — pkg108/pkg86-B/pkg116/pkg88-C.0/pkg115 chunk 1 COMPLETE + pkg114 inc 1+2)
**Prepared by:** Claude (Anthropic Code) — rewritten at the 2026-06-11 round closeout (8 PRs: pkg108/pkg86-B/pkg116/pkg88-C.0/pkg115 chunk 1 autonomous; pkg114 inc 1+2 by parallel Opus agent).
**Scope:** post-2026-06-11 next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> Round 15 Wave 6 section is authoritative for the current state).

> ⚠️ **UPDATE 2026-06-11:** **5 packages shipped this round** (all RTX-verified; final sweep
> on merged main 75185a6: 1214 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed).
> **pkg108 DONE** (PR #432 — addon residual bug triage: BUG-14 GPU glass tint fix, BUG-16
> GPU subsurface fix, BUG-09 live-Blender verified). **pkg86-B DONE** (PRs #434/#436/#438 —
> GPU light tree Phases 2+3: device traversal mirrors Cycles, pick parity ≥99.5%/10k queries,
> upload 0.09–0.5ms @10k lights, SAOH two-cluster routing >95% both backends; GPU variance
> 1.110× — 2.0× gate xfail on BOTH backends, Phase-1 scene-structure limitation). **pkg116
> DONE** (PR #435 — exporter/cache refactor: 135 addon tests green, zero existing-test edits).
> **pkg88 Phase C.0 DONE** (PR #437 — deformation motion blur: union-AABB BVH, time-aware
> Triangle::hit + GPU, GRay.time end-to-end both megakernels; REMAINING: C.1 per-primitive
> split, Phase B addon bake after pkg114 inc3, Phase D wavefront after pkg55-B). **pkg115
> Stage 2 chunk 1 DONE** (PR #439 — procedural texture parity: research audit + GENERATED
> coord default + Checker/Gradient/Magic Cycles parity; REMAINING chunks: hash/WhiteNoise →
> Perlin/Noise → Wave → Brick → Voronoi). **pkg114 inc 1+2** (PRs #430/#431 by parallel
> Opus agent, not this session).
>
> **3 xpassed gates now PASS** (total_max_depth caps, filter_glossy, reflective-caustics
> flags) — promote to live tests next round. **Expected suite state:** 0 failures / 20 xfails
> (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others).
>
> The next autonomous lead pool is **pkg55 Phase B** (wavefront shade kernels — start after
> pkg114 inc3 merges, both touch GPU kernels) → **pkg115 chunks 2+** (hash/WhiteNoise →
> Perlin/Noise → Wave → Brick → Voronoi) → **pkg88 C.1** (perf-gated per-primitive split) +
> **Phase B** (addon bake, after pkg114 inc3) → **pkg64** (spectral caustics, huge). All
> GPU-gated + RTX-verifiable.
>
> **Owner directives (2026-06-08):** (1) **Pillar 4 (pkg45/46/48/49/50/51 + pkg107) is ON
> PAUSE** until the rest is working/stable/sufficiently progressed — do not pick it up.
> (2) The broken old-Blender benchmark scenes (Classroom/BMW27/Junkshop/UDIM_monster) were
> **removed**; **pkg76 Classroom/BMW27/Junkshop fidelity is dropped** from the pool.
> cornell is the only remaining Cycles-parity scene.

---

## 1. Current state (one screen)

- **5 packages shipped this round (2026-06-11).** pkg108 DONE (PR #432 — addon residual bug
  triage: BUG-14 GPU glass tint fix, BUG-16 GPU subsurface fix, BUG-09 live-Blender verified).
  pkg86-B DONE (PRs #434/#436/#438 — GPU light tree: device traversal, pick parity ≥99.5%/10k,
  upload 0.09–0.5ms @10k lights, SAOH routing >95% both backends; GPU variance 1.110×, 2.0×
  gate xfail both backends). pkg116 DONE (PR #435 — exporter/cache refactor: 135 addon tests
  green). pkg88 Phase C.0 DONE (PR #437 — deformation motion blur: union-AABB BVH, time-aware
  Triangle::hit + GPU, GRay.time end-to-end; REMAINING: C.1/B/D). pkg115 chunk 1 DONE (PR #439
  — procedural texture parity: research audit + GENERATED coord + Checker/Gradient/Magic;
  REMAINING: hash → Perlin → Wave → Brick → Voronoi). pkg114 inc 1+2 (PRs #430/#431 by
  parallel Opus agent).
- **RTX sweep on merged main 75185a6: 1214 passed / 0 failed / 23 skipped / 20 xfailed / 3
  xpassed.** The 3 xpassed gates (total_max_depth caps, filter_glossy, reflective-caustics
  flags) now PASS and should be promoted to live tests next round. **Expected suite state:**
  0 failures / 20 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others).
- **pkg64-gpu SMS gates drift RESOLVED (2026-06-08).** Evidence doc
  `pkg64-gpu-hw-sweep-2026-05-31.md` RESOLUTION section: PSNR gate re-blessed (GPU output
  legitimately improved after #404 glass fix); SSIM parity gate xfail'd as legacy (the SMS-GPU
  path is frozen, no further SMS-GPU work). The SSIM gate was stale vs STATUS.md §2 item 6.
- **Blender 5.1 is installed on this machine.** Agents CAN now re-bless cross-engine Cycles
  references (PR #410 proves it).
- **No open PRs.** The PR queue is empty.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg55 Phase B (wavefront shade kernels
  — start after pkg114 inc3 merges, both touch GPU kernels) → pkg115 chunks 2+ → pkg88 C.1 +
  Phase B (after pkg114 inc3) → pkg64 (spectral caustics). Pillar 4 (pkg45/46/48/49/50/51 +
  pkg107) ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. **pkg108, pkg86-B, pkg116, pkg88 C.0, pkg115
chunk 1 are DONE** (closed this round). CI is **Linux/CPU only** — pick CPU work whose
correctness can be gated without a GPU.

**Top priority (autonomous, GPU-gated — do on RTX):**

1. **pkg55 Phase B — wavefront shade kernels** (GPU, large, research already signed off per
   its spec). Laine 2013 per-material shade kernels; the pkg81-measured viewport-parity
   blocker (CUDA 104 ms vs CPU 58 ms — megakernel register pressure). Multi-session.
   **Start after pkg114 inc3 merges** (both touch GPU kernels; inc3 is in flight by parallel
   Opus agent).
2. **pkg115 chunks 2+ — procedural texture parity continuation** (GPU visual verify, multi-
   session). Audit §6 order 5–10: util/hash + White Noise → Perlin + fractal stack + Noise
   node (musgrave alias; `noise.h` is BSD-3-Clause) → Wave → Brick → Voronoi → addon
   translator dedup + standalone CI example + RTX visual verify vs Cycles. Chunk 1 DONE
   (PR #439).
3. **pkg88 C.1 — per-primitive motion blur split** (perf-gated B/C4 decision per spec).
   Phase C.0 DONE (PR #437); C.1 is the Cycles `prim_time` early-out split only if measured
   regression vs Cycles justifies the complexity. **Phase B** (addon bake) — start after
   pkg114 inc3 merges (same addon area). **Phase D** (wavefront SoA integration) — after
   pkg55-B.
4. **pkg64 — spectral caustics** (huge, ~3–4 wk). The SMS CPU spectral caustic path.

**GPU-gated pool (previously OWNER-BLOCKED, now autonomous after this round's merges):**

5. **pkg55-B' CUDA sessions** (wavefront port continuation after Phase B — per-material
   shade kernels). Multi-session GPU-gated work.
6. **SPPM-progressive + VCM** (owner decision). GPU-gated; CI has no GPU.

**Pillar 4 (PAUSED per owner directive 2026-06-08):**

- **pkg45/46/48/49/50/51 + pkg107** — all ON PAUSE until core rendering is
  working/stable/sufficiently progressed. **Do NOT pick up Pillar-4 specs.**

**Note on test suite:** The full local test suite has **ZERO failures** (expected suite
state: 0 failures / 20 xfails). The 3 xpassed gates (total_max_depth caps, filter_glossy,
reflective-caustics flags) now PASS — promote to live tests next round. The 20 xfails are
legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others. The previous pkg64-gpu
parity SSIM xfail (item 6 in the prior report) is RESOLVED (xfail'd as legacy per
`pkg64-gpu-hw-sweep-2026-05-31.md` RESOLUTION section).

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, full local test + stale-call-site sweep before each push, poll CI then
`gh pr merge --squash --delete-branch`.** **Start with pkg55 Phase B** (§2 item 1 —
wavefront shade kernels; wait for pkg114 inc3 to merge first, both touch GPU kernels)
or **pkg115 chunks 2+** (§2 item 2 — hash/WhiteNoise → Perlin/Noise → Wave → Brick →
Voronoi). Both are GPU-gated + RTX-verifiable. Cite papers per CLAUDE.md §6 for any
new algorithm (`/cite-algorithm`); for pkg115 the sources are Cycles `svm/noise.h` +
`voronoi.h` + `wave.h` + etc. (BSD-3-Clause for Perlin/fractal stack). The next round
is GPU-heavy; clean CI-only CPU wins are exhausted after this round's pkg108/pkg116/etc.

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
- **Promote the 3 xpassed gates next round** — `total_max_depth` caps, `filter_glossy`,
  reflective-caustics flags now PASS (spectral path_tracer ported them); remove the xfail
  decorators and move them to live tests.

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
