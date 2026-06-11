# Astroray Next Stage Report

**Date:** 2026-06-12 overnight (Round closeout — pkg55-B' Phase B' COMPLETE — viewport-parity gate MET: wavefront p99 = 0.84× Cycles)
**Prepared by:** Claude (Anthropic Code) — rewritten at the 2026-06-12 overnight round closeout (5 PRs: pkg55-B' Phase B' complete + pkg114 inc3a+3b).
**Scope:** post-2026-06-12-overnight next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> 2026-06-12 overnight round is authoritative for the current state).

> ⚠️ **UPDATE 2026-06-12 overnight:** **pkg55-B' Phase B' COMPLETE** (all RTX-verified; final sweep on merged main 3804dca: 1277 passed / 0 failed / 23 skipped / 22 xfailed / 2 xpassed).
> **pkg55-B' Phase B' DONE** (PRs #459/#461/#463, 2026-06-12 — all three acceptance criteria MET): perf gate 1.50× (PR #459 cool-GPU re-baseline — formal gate run measured 1.50×, floor PASSED, 1.5× target XPASSED; Phase-B perf criterion recorded as MET); wavefront_path_tracer registered (PR #459 — decorator over path_tracer, CPU delegates, GPU routes to cuda_wavefront_render, `gpuSupported==True`, megakernel fallback when build lacks ASTRORAY_WAVEFRONT_CUDA_N3; 3 tests pass); viewport-parity gate MET (PR #461 persistent context + single-wave fast path + double-scene-flatten dispatch fix, then PR #463 in-Blender Cycles A/B — **wavefront steady-state pan-frame p99 = 0.84× Cycles-OPTIX, target ≤1.2×; mean 0.97×, p50 0.98× — parity-or-faster on every statistic**; full suite 1277/0 incl. pkg114 inc3a/3b's new TLAS tests got incidental RTX verification). **The "viewport feels like a slog" complaint is formally resolved.** Phase C (MIS audit + megakernel removal + 2× gate) remains. Deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch.
>
> **pkg114 inc3a+3b landed** (PRs #460/#462, dedicated pkg114 agent): inc 3a = `register_mesh_bulk` binding (object-local UVs/smooth normals/multi-material into shared BLAS; RTX: 2 instances vs baked, BLAS sharing 8 prims vs 16). inc 3b = MIXED instanced + non-instanced GPU scenes (flat scene uploaded first at offset 0, exposed as one identity-transform instance; `gpu_tlas_hit` traverses flat+instanced uniformly; no device change; flat-scene area lights now resolve in mixed scenes; RTX: floor + 3 instanced tetrahedra == fully-baked; broad GPU regression sweep clean). **REMAINING (inc 3c):** addon `convert_objects` instancing wiring + depsgraph transform-only refit (TLAS-only re-upload for pkg56 ≤50%-baseline budget).
>
> **2 xpassed gates** (down from 6 — 4 promoted or returned to xfail status). **Expected suite state:** 0 failures / 22 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others).

---

## 1. Current state (one screen)

- **pkg55-B' Phase B' COMPLETE this round (2026-06-12 overnight).** All three Phase-B' acceptance criteria MET (PRs #459/#461/#463 — perf gate 1.50× @ 512spp, wavefront_path_tracer registered with `gpuSupported==True`, viewport-parity gate: wavefront p99 = 0.84× Cycles-OPTIX — DECISIVELY inside ≤1.2× target; mean 0.97×, p50 0.98×). The "viewport feels like a slog" complaint is formally resolved. Phase C (MIS audit + megakernel removal + 2× gate) remains open as the package's final phase. Deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch.
- **pkg114 inc3a+3b landed** (PRs #460/#462, dedicated pkg114 agent — RTX-verified): register_mesh_bulk binding + MIXED instanced/non-instanced GPU scenes. REMAINING (inc 3c): addon `convert_objects` instancing wiring + depsgraph transform-only refit.
- **RTX sweep on merged main 3804dca: 1277 passed / 0 failed / 23 skipped / 22 xfailed / 2 xpassed.** The 2 xpassed gates are spectral-path-tracer ported flags. **Expected suite state:** 0 failures / 22 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others).
- **Blender 5.1 is installed on this machine.** Agents CAN now re-bless cross-engine Cycles references (PR #410 proves it).
- **No open PRs.** The PR queue is empty.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg55 Phase C (megakernel removal + MIS audit + 2× gate) → pkg115 dedup + RTX visual verify → pkg88 C.1 + Phase B (after pkg114 inc3c) → pkg64 (spectral caustics, huge). Pillar 4 (pkg45/46/48/49/50/51 + pkg107) ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. **pkg55-B' Phase B' is DONE** (closed this round — viewport-parity gate MET). CI is **Linux/CPU only** — pick CPU work whose correctness can be gated without a GPU.

**Top priority (autonomous, GPU-gated — do on RTX):**

1. **pkg55 Phase C — megakernel removal + MIS audit + 2× gate** (GPU, large ~3 weeks). With Phase B' complete, Phase C removes the megakernel code paths and demonstrates ≥ 2× end-to-end speedup on the Disney contact-sheet scene (7 material types, 1024 SPP) compared to the Phase A megakernel baseline. MIS balance heuristic ported (power-heuristic MIS weighting); ReSTIR reservoirs migrated to GPU SoA if needed. All pkg54/54a/54b SSIM gates must pass with megakernel deleted. Deferred items from Phase B': non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch.
2. **pkg115 dedup + RTX visual verify** (GPU visual verify, small). Addon-side private texture-definition duplication removal (Approach step 4) + Blender-vs-Cycles paired-still RTX visual (`/verify`). **Chunks 1-5 DONE** (PRs #439/#441/#442/#445/#446 — Noise/Wave/Brick/Voronoi Cycles parity complete).
3. **pkg88 C.1 — per-primitive motion blur split** (perf-gated B/C4 decision per spec). Phase C.0 DONE (PR #437); C.1 is the Cycles `prim_time` early-out split only if measured regression vs Cycles justifies the complexity. **Phase B** (addon bake) — start after pkg114 inc3c merges (same addon area). **Phase D** (wavefront SoA integration) — after pkg55 Phase C.
4. **pkg64 — spectral caustics** (huge, ~3–4 wk). The SMS CPU spectral caustic path.
5. **xpassed-gate promotions** (small). The 2 xpassed gates (spectral-path-tracer ported flags) now PASS — promote to live tests if they still pass on next hardware sweep. Remove xfail decorators.

**GPU-gated pool:**

6. **SPPM-progressive + VCM** (owner decision). GPU-gated; CI has no GPU.

**Pillar 4 (PAUSED per owner directive 2026-06-08):**

- **pkg45/46/48/49/50/51 + pkg107** — all ON PAUSE until core rendering is
  working/stable/sufficiently progressed. **Do NOT pick up Pillar-4 specs.**

**Note on test suite:** The full local test suite has **ZERO failures** (expected suite
state: 0 failures / 22 xfails). The 2 xpassed gates (spectral from earlier) now PASS — promote candidates to live tests next round. The 22 xfails are legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others.

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, full local test + stale-call-site sweep before each push, poll CI then
`gh pr merge --squash --delete-branch`.** **Start with pkg55 Phase C** (§2 item 1 — megakernel removal, MIS audit, 2× gate on Disney contact-sheet 1024spp vs Phase-A baseline) or **pkg115 dedup + RTX visual verify** (§2 item 2 — addon-side texture duplication removal + Blender-vs-Cycles paired-still RTX visual). Both are GPU-gated + RTX-verifiable. Cite papers per CLAUDE.md §6 for any new algorithm (`/cite-algorithm`). The next round is GPU-heavy; clean CI-only CPU wins are exhausted.

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
- **Promote the 2 xpassed gates next round** — 2 spectral-path-tracer flags now PASS; remove xfail decorators and move to live tests.

---

## 5. After the round

- Flip any landed spec `Status:` lines to `done (PR #N, date — headline numbers)`.
- Update STATUS.md (new round section + the next pickup queue), ROADMAP.md (pillar
  status + long-tail), and rewrite this report's §1/§2 for the next round.
- Run the RTX hardware sweep; re-confirm all merged PRs hold on hardware (caustics, glass,
  motion blur, light tree, etc.). Record the full test-suite state (passed/failed/skipped/
  xfailed/xpassed counts).
- Promote the 2 xpassed gates to live tests if they still pass.
- Open ONE doc PR for the closeout; it is doc-only and auto-merge eligible.
