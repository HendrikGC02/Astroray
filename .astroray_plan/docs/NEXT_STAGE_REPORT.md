# Astroray Next Stage Report

**Date:** 2026-06-12 evening (Stabilization + showcase + portability session)
**Prepared by:** Claude (Anthropic Code) — updated after the 2026-06-12 stabilization session (repo cleanup; full main-checkout build; RTX sweep 1299/0; README + report deliverables; RTX-3000 portability).
**Scope:** post-2026-06-12 next stage. **The next arc is pkg55 Phase C** (§2 item 1 — MIS audit + megakernel removal + 2× perf gate).

> ⚠️ **UPDATE 2026-06-12 evening (stabilization session):** Fresh full-featured build in the MAIN checkout (CUDA 12.8 + OptiX 9.1 + OIDN + tcnn, arch 75;86;89 — now portable to RTX 3000/sm_86). Full RTX sweep on b67b50f: **1299 / 0 / 14 skipped / 21 xfailed / 3 xpassed**; pkg55 perf gate re-confirmed **1.50×** cool-run isolated. PR #474 (gradient/magic id(node) cache aliasing) **verified visually** in headless Blender — all 8 procedural textures correct on the addon CPU path. Reference bank 12/13 PASS (prism-bk7 gate calibration stale since the #400 recompose — render visually perfect, SSIM 0.9953; recalibrate as follow-up). pkg89 dedicated-light gaps re-confirmed live (GPU leg dark, CPU exposure dim vs Cycles) — unchanged priority. README showcase renders refreshed per owner feedback; `docs/reports/2026-06-feature-showcase.html` + `docs/DEVELOPMENT.md` shipped.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> 2026-06-12 overnight round is authoritative for the current state).

> ⚠️ **UPDATE 2026-06-12 morning:** **pkg115 COMPLETE** (all RTX-verified; final sweep on merged main f11085c: 1289 passed / 0 failed / 23 skipped / 21 xfailed / 3 xpassed).
> **pkg115 DONE** (PRs #467/#471/#472, 2026-06-12 — all Stage 2 chunks + GENERATED coords fix landed): chunk 6 addon dedup (#467 — unified procedural param mappings onto Cycles-parity ports; review caught a shipped RIDGED↔HYBRID enum swap, fixed); visual-gate diagnosis (#471 — 4 root causes: GPU dark = pkg89 dedicated lights not uploaded; CPU hang = OpenMP deadlock inside Blender generalized to MSVC — **ALL addon builds need `-DASTRORAY_DISABLE_OPENMP=ON`**; harness sample property; UV-vs-GENERATED space); GENERATED coords fix (#472 — `Texture::setGeneratedBBox` + addon bakes world bbox per object; **128-spp Blender stills: checker=3D blocks, brick=brickwork, wave=bands, voronoi patterned — semantic parity with Cycles**; full suite 1289/0). **Remaining small follow-ups recorded in spec:** gradient + noise spheres near-black on addon path; pkg89 dedicated-light energy audit; per-object texture instancing.
>
> **pkg114 inc 3d landed** (PR #468, dedicated agent): TLAS-only refit for transform-only edits (`updateInstanceTransform` + `uploadInstanceTransforms` re-push only `d_instances`+`d_tlas` — **no BLAS geometry walk**; refit upload **19.5%** of full `upload_geometry` on 3200-tri ×16-instance, ≤50% budget met; byte-identical vs from-scratch rebuild). **REMAINING (inc 3c+3d integration):** addon `convert_objects` instancing wiring + exporter `Change.TRANSFORMS` branch wiring to `updateInstanceTransform` (instance-id map).
>
> **3 xpassed gates** (up from 2 — 1 new spectral flag promoted). **Expected suite state:** 0 failures / 21 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others).

---

## 1. Current state (one screen)

- **pkg115 COMPLETE this round (2026-06-12 morning).** All Stage 2 chunks + GENERATED-coordinates mesh fix landed (PRs #467/#471/#472 — chunk 6 addon dedup; visual-gate diagnosis: GPU dark = pkg89, CPU hang = OpenMP deadlock generalized to MSVC; GENERATED coords fix: 128-spp Blender stills show semantic parity with Cycles; full suite 1289/0). **Remaining small follow-ups recorded in spec:** gradient + noise spheres near-black on addon path; pkg89 dedicated-light energy audit; per-object texture instancing for shared materials.
- **pkg114 inc 3d landed** (PR #468, dedicated agent — RTX-verified): TLAS-only refit for transform-only edits (refit upload 19.5% of full `upload_geometry`, ≤50% budget met; byte-identical vs from-scratch rebuild). REMAINING (inc 3c+3d integration): addon `convert_objects` instancing wiring + exporter `Change.TRANSFORMS` branch wiring to `updateInstanceTransform` (instance-id map).
- **RTX sweep on merged main f11085c: 1289 passed / 0 failed / 23 skipped / 21 xfailed / 3 xpassed.** The 3 xpassed gates are spectral-path-tracer ported flags. **Expected suite state:** 0 failures / 21 xfails (legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others).
- **Blender 5.1 is installed on this machine.** Agents CAN now re-bless cross-engine Cycles references (PR #410 proves it).
- **No open PRs.** The PR queue is empty.
- **Next autonomous work: GPU-gated + RTX-verifiable.** pkg55 Phase C (megakernel removal + MIS audit + 2× gate) → pkg114 inc 3c+3d integration → pkg88 C.1 + Phase B (after pkg114 inc3c) → pkg64 (spectral caustics, huge). Pillar 4 (pkg45/46/48/49/50/51 + pkg107) ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. **pkg115 is DONE** (closed this round — Cycles-parity textures + GENERATED coords fix). CI is **Linux/CPU only** — pick CPU work whose correctness can be gated without a GPU.

**Top priority (autonomous, GPU-gated — do on RTX):**

1. **pkg55 Phase C — megakernel removal + MIS audit + 2× gate** (GPU, large ~3 weeks). With Phase B' complete (viewport-parity gate MET last round), Phase C removes the megakernel code paths and demonstrates ≥ 2× end-to-end speedup on the Disney contact-sheet scene (7 material types, 1024 SPP) compared to the Phase A megakernel baseline. MIS balance heuristic ported (power-heuristic MIS weighting); ReSTIR reservoirs migrated to GPU SoA if needed. All pkg54/54a/54b SSIM gates must pass with megakernel deleted. Deferred items from Phase B': non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch.
2. **pkg114 inc 3c+3d integration — addon instancing wiring + exporter transform-only dispatch** (GPU, small). Inc 3d (TLAS-only refit) DONE (PR #468); remaining: addon `convert_objects` instancing wiring (GPU pre-check, group by `(obj.data, obj.name)` count ≥ 2, register_mesh_bulk once + add_instance per instance) + exporter `Change.TRANSFORMS` branch wiring to `updateInstanceTransform` (instance-id map). Headless Blender 5.1 verification. This closes the pkg56 ≤50%-baseline transform-only budget gate.
3. **pkg115 small follow-ups** (GPU visual verify, small). Gradient + noise spheres near-black on addon path (two evaluator/translation bugs); pkg89 dedicated-light energy-scale audit (dimmer than Cycles at equal wattage); per-object texture instancing for shared materials. List these in §2 as a small cleanup package candidate.
4. **pkg88 C.1 — per-primitive motion blur split** (perf-gated B/C4 decision per spec). Phase C.0 DONE (PR #437); C.1 is the Cycles `prim_time` early-out split only if measured regression vs Cycles justifies the complexity. **Phase B** (addon bake) — start after pkg114 inc3c merges (same addon area). **Phase D** (wavefront SoA integration) — after pkg55 Phase C.
5. **pkg64 — spectral caustics** (huge, ~3–4 wk). The SMS CPU spectral caustic path.
6. **xpassed-gate promotions** (small). The 3 xpassed gates (spectral-path-tracer ported flags) now PASS — promote to live tests if they still pass on next hardware sweep. Remove xfail decorators.

**Stabilization-session follow-ups (2026-06-12, record-only — small):**

- **Refbank prism-bk7 gate recalibration**: `hue_spread`/`bright_coverage` thresholds date from the pre-#400 wide comp; the 512² "pkg104 showcase" recompose makes them unreachable (measured 0.33/0.47 vs ≥0.7/≥0.5) while the render is visually perfect and SSIM = 0.9953 vs the re-blessed reference. Recalibrate gates.toml to the current framing.
- **Refbank stale-reference hygiene**: two references re-blessed this session (prism-bk7 was 384×288 vs the 512² scene — crashed the runner; sms-refractive-glass-sphere predated the June glass-energy arc — phash 18 vs ≤16). Consider a runner pre-flight that flags reference/scene resolution mismatches instead of crashing mid-sweep.
- **`raytracer.exe` DLL convenience**: the standalone needs OIDN + CUDA runtime DLLs on PATH (documented in DEVELOPMENT.md); a CMake post-build copy next to the exe would remove the footgun.
- **pkg89 dedicated lights** (re-confirmed live this session): not uploaded to GPU (pkg115 texture grid GPU leg renders dark) + CPU energy-scale uniformly dimmer than Cycles at equal wattage. Already §2 item 3.
- **pkg64 walltime load-robustness** (chip filed earlier): no flakes in today's sweep, even under addon-build load — keep the chip, don't escalate.
- **viewport_parity `--tag` quirk**: the tag *replaces* the output filename stem instead of suffixing it (a second Astroray leg overwrote the first this session). One-line fix in `blender_driver.py`.
- **pkg74 runner**: must be invoked as `python -m benchmarks.showcase.runner` (relative imports); direct-path invocation traps the unwary.

**GPU-gated pool:**

6. **SPPM-progressive + VCM** (owner decision). GPU-gated; CI has no GPU.

**Pillar 4 (PAUSED per owner directive 2026-06-08):**

- **pkg45/46/48/49/50/51 + pkg107** — all ON PAUSE until core rendering is
  working/stable/sufficiently progressed. **Do NOT pick up Pillar-4 specs.**

**Note on test suite:** The full local test suite has **ZERO failures** (expected suite
state: 0 failures / 21 xfails). The 3 xpassed gates (spectral from earlier) now PASS — promote candidates to live tests next round. The 21 xfails are legacy pkg64-gpu SMS gates + pkg86 2× variance gates + others.

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, full local test + stale-call-site sweep before each push, poll CI then
`gh pr merge --squash --delete-branch`.** **Start with pkg55 Phase C** (§2 item 1 — megakernel removal, MIS audit, 2× gate on Disney contact-sheet 1024spp vs Phase-A baseline) or **pkg114 inc 3c+3d integration** (§2 item 2 — addon instancing wiring + exporter transform-only dispatch; closes pkg56 ≤50%-baseline budget gate). Both are GPU-gated + RTX-verifiable. Cite papers per CLAUDE.md §6 for any new algorithm (`/cite-algorithm`). The next round is GPU-heavy; clean CI-only CPU wins are exhausted.

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
- **Promote the 3 xpassed gates next round** — 3 spectral-path-tracer flags now PASS; remove xfail decorators and move to live tests.
- **OpenMP deadlock generalized to MSVC** (PR #471) — ALL addon-use builds need `-DASTRORAY_DISABLE_OPENMP=ON`, not just MinGW (memory update pending).

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
