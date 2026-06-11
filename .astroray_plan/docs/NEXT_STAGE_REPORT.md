# Astroray Next Stage Report

**Date:** 2026-06-11 afternoon (Round closeout — pkg115 chunks 2-5 COMPLETE + pkg55-B' Sessions N+6/N+7 COMPLETE)
**Prepared by:** Claude (Anthropic Code) — rewritten at the 2026-06-11 afternoon round closeout (8 PRs: pkg115 chunks 2-5 + pkg55-B' Sessions N+6/N+7 parts 1-2 autonomous).
**Scope:** post-2026-06-11-afternoon next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> Round 15 Wave 6 section is authoritative for the current state).

> ⚠️ **UPDATE 2026-06-11 afternoon:** **2 packages advanced major steps this round** (all RTX-verified; final sweep on merged main 5e21bd5: 1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed).
> **pkg115 chunks 2-5 DONE** (PRs #441/#442/#445/#446 — Noise/Wave/Brick/Voronoi Cycles parity: Jenkins lookup3 hash bit-exact + Perlin core BSD-3-Clause + fractal stack + WhiteNoiseTexture + NoiseTextureCycles; Wave fixes ~6.4× density bug + signed-fBM detail distortion; Brick 3D input + per-brick color variation; full Cycles-parity Voronoi with distance metrics/Features/fractal layering/node conditioning, lead-review fixes; addon ShaderNodeTexVoronoi translation + factory full-param wiring fixes latent regression. 1271 passed, 0 failed. pkg98 SIGN-OFF chunks 2-3. REMAINING: addon-side texture duplication removal + RTX visual verify). **pkg55-B' Sessions N+6/N+7 DONE** (PRs #443/#444/#447/#448 — GPU wavefront now produces IMAGES at megakernel parity: N+6 = end-to-end pipeline with `stage_advance.cu` one-bounce device twin calling UNMODIFIED megakernel device functions (design decision #9), `gpu_env_spectral.cuh` env-miss factored verbatim, `cuda_wavefront_render` host driver; measured GPU-WF/CPU-WF [1.089, 0.991, 1.045] gate ≤0.12. PR #444 root-caused ~1.85× "MAJOR FINDING" as measurement artifact (applyGamma=True vs linear oracle) AND fixed real latent bug (megakernel ignored worldMaxBounces). N+7 part 1 = host-overhead elimination: device-side XYZ accumulation, ONE sync + ONE download per render; wavefront 0.300 s → 0.108 s (2.8× faster), gap to megakernel 1.55×. pkg98 SIGN-OFF (Opus) part 1. N+7 part 2 = alive-queue compaction — MEGAKERNEL PARITY: shared `advancePathSlot`, ping-pong slot queues with device-side counters; measured wavefront 0.074 s vs megakernel 0.070 s — 1.05× (from 1.55× part 1, 4.0× N+6); WF/MK image ratio unchanged to 7 decimals [0.997, 0.999, 0.997]; full suite 1271 passed / 0 failed. pkg98 SIGN-OFF (Opus) part 2. REMAINING for B' close: N+7 part 3 sort-by-material + intersect/shade split for 254-reg cliff + ≥1.5×-FASTER gate, wavefront_path_tracer plugin registration, 7-material contact-sheet perf gate, pkg81 viewport-parity gate).
>
> **3 xpassed gates STILL PASS** (total_max_depth caps, filter_glossy, reflective-caustics flags) — promote to live tests next round. **Expected suite state:** 0 failures / 20 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others). pkg114 inc3 (addon instancing) still pending with dedicated agent.
>
> The next autonomous lead pool is **pkg55 Phase B completion** (N+7 part 3 sort-by-material + intersect/shade split + plugin registration + perf gates) → **pkg115 dedup + RTX visual verify** → **pkg88 C.1** (perf-gated per-primitive split) + **Phase B** (addon bake, after pkg114 inc3) → **pkg64** (spectral caustics, huge). All GPU-gated + RTX-verifiable.
>
> **Owner directives (2026-06-08):** (1) **Pillar 4 (pkg45/46/48/49/50/51 + pkg107) is ON
> PAUSE** until the rest is working/stable/sufficiently progressed — do not pick it up.
> (2) The broken old-Blender benchmark scenes (Classroom/BMW27/Junkshop/UDIM_monster) were
> **removed**; **pkg76 Classroom/BMW27/Junkshop fidelity is dropped** from the pool.
> cornell is the only remaining Cycles-parity scene.

---

## 1. Current state (one screen)

- **2 packages advanced major steps this round (2026-06-11 afternoon).** pkg115 chunks 2-5 DONE (PRs #441/#442/#445/#446 — Noise/Wave/Brick/Voronoi Cycles parity: Jenkins hash bit-exact + Perlin BSD-3 + fractal stack + WhiteNoiseTexture + NoiseTextureCycles; Wave fixes ~6.4× density bug; Brick per-brick color variation; full Voronoi with lead-review fixes; addon ShaderNodeTexVoronoi translation fixes latent regression. pkg98 SIGN-OFF chunks 2-3. REMAINING: addon duplication removal + RTX visual verify). pkg55-B' Sessions N+6/N+7 DONE (PRs #443/#444/#447/#448 — GPU wavefront now produces IMAGES at megakernel parity: N+6 end-to-end pipeline calling UNMODIFIED megakernel device functions (design decision #9), GPU-WF/CPU-WF [1.089, 0.991, 1.045] gate ≤0.12; PR #444 root-caused ~1.85× as measurement artifact + fixed real worldMaxBounces bug; N+7 part 1 host-overhead elimination → wavefront 0.300 s → 0.108 s (1.55× vs megakernel); N+7 part 2 alive-queue compaction → wavefront 0.074 s vs megakernel 0.070 s — MEGAKERNEL PARITY 1.05×; WF/MK image ratio [0.997, 0.999, 0.997]; full suite 1271 passed / 0 failed. pkg98 SIGN-OFF (Opus) parts 1-2. REMAINING: N+7 part 3 sort-by-material + intersect/shade split + plugin registration + perf gates).
- **RTX sweep on merged main 5e21bd5: 1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed.** The 3 xpassed gates (total_max_depth caps, filter_glossy, reflective-caustics flags) STILL PASS and should be promoted to live tests next round. **Expected suite state:** 0 failures / 20 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others). pkg114 inc3 (addon instancing) still pending with dedicated agent.
- **Blender 5.1 is installed on this machine.** Agents CAN now re-bless cross-engine Cycles references (PR #410 proves it).
- **No open PRs.** The PR queue is empty.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg55 Phase B completion (N+7 part 3 + plugin registration + perf gates) → pkg115 dedup + RTX visual verify → pkg88 C.1 + Phase B (after pkg114 inc3) → pkg64 (spectral caustics). Pillar 4 (pkg45/46/48/49/50/51 + pkg107) ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. **pkg115 chunks 2-5, pkg55-B' Sessions N+6/N+7 are DONE** (closed this round). CI is **Linux/CPU only** — pick CPU work whose correctness can be gated without a GPU.

**Top priority (autonomous, GPU-gated — do on RTX):**

1. **pkg55 Phase B completion — N+7 part 3 + plugin registration + perf gates** (GPU, multi-session). N+7 part 3 = sort-by-material + intersect/shade split targeting the 254-reg cliff + the ≥1.5×-FASTER gate (needs warp-coherent shading per Laine 2013). Then: `wavefront_path_tracer` plugin registration, 7-material contact-sheet perf gate, pkg81 viewport-parity gate (the pkg81-measured CUDA 104 ms vs CPU 58 ms blocker — megakernel register pressure). Deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch. **Sessions N+6/N+7 parts 1-2 DONE** (PRs #443/#444/#447/#448, 2026-06-11 — MEGAKERNEL PARITY 1.05×).
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
`gh pr merge --squash --delete-branch`.** **Start with pkg55 Phase B completion** (§2 item 1 — N+7 part 3 sort-by-material + intersect/shade split targeting the 254-reg cliff + the ≥1.5×-FASTER gate, then wavefront_path_tracer plugin registration + 7-material contact-sheet perf gate + pkg81 viewport-parity gate) or **pkg115 dedup + RTX visual verify** (§2 item 2 — addon-side texture duplication removal + Blender-vs-Cycles paired-still RTX visual). Both are GPU-gated + RTX-verifiable. Cite papers per CLAUDE.md §6 for any new algorithm (`/cite-algorithm`); for pkg55 N+7 part 3 the sources are Laine 2013 (DOI 10.1145/2492045.2492060) + Cycles `kernel/integrator/shade_surface.h` (Apache-2.0). The next round is GPU-heavy; clean CI-only CPU wins are exhausted after the morning round's pkg108/pkg116/etc.

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
