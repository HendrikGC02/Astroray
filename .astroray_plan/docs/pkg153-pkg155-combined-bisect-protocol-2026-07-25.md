# Combined bisect protocol — pkg155 (GPU perf/occupancy) + pkg153 (R-channel env drift)

**Filed:** 2026-07-25 overnight (architect), folding in the team-lead's pkg155
Phase 1 findings (`.astroray_plan/docs/pkg155-phase1-profile-findings.md`,
measured @ `473c25b`, RTX 5070 Ti, CUDA 12.8.61).
**Owners:** pkg155 (Phase 2) and pkg153 (disposition) both execute against THIS
protocol. Neither runs a separate bisect.
**Status of this doc:** ready to execute under the serialized GPU lock. Docs-only
tonight; no build, no render, no code was run to produce it.

---

## 0. Why combine

pkg155 and pkg153 bisect the **same merge window** (#481 → #524) on the **same
single GPU**. A full CUDA rebuild is the most expensive resource in the loop, and
two independent bisects double it for no reason: the R-channel drift (pkg153) and
the register/occupancy growth (pkg155) both live in the **shared spectral device
shading path** that the megakernel and the wavefront shade stage each `#include`.
This protocol captures **all four signals from ONE build per bisect point.**

Phase 1 makes the combination far cheaper than the architect's first estimate:
the **primary bisect signal is now a compile-time register count**, not a timed
render — deterministic, zero timing noise, and readable from a build without a
GPU render.

## 1. The four signals, captured from ONE build per point

| # | Signal | Owner | How | Needs a render? |
|---|---|---|---|---|
| 1 | **Shade-path regs/thread** (PRIMARY bisect signal) | pkg155 | `ptxas -v` at compile / `cuobjdump --dump-resource-usage` on the built module | **No** — compile-time |
| 2 | Total GPU kernel-ms/render | pkg155 | `benchmarks/wavefront_baseline.py --spp 64 --max-depth 8`, cornell_diffuse+glass, 256², 1 warmup + 5 measured, `sum_ms ÷ renders` (Phase 1 §0 corrected metric) | Yes |
| 3 | R-channel env-scene GPU/CPU mean ratio | pkg153 | the three failing gates' open-env scene (warm emissive sphere), per-channel mean ratio; plus the emitters→matte env-only discriminator (pkg153 C7 finding) | Yes |
| 4 | tables-loaded checksum | pkg153 | verify the spectral/glass LUTs actually resident at this commit (a build can silently ship without them) | build probe |

**Signal 1 detail (the sharp one).** Register growth is the *proximate cause* of
the occupancy loss (Phase 1 §3: shade at 221 regs → 1 block/SM; target ≤128 for
2 blocks/SM). Capture two register tracks per point so the bisect is robust to
the kernel-identity change across the window:

- **MW megakernel regs** — the *continuous* cross-window probe. The
  `multiwavelength_megakernel` exists from #481 through `e0185c8` (deleted only at
  #524), and its documented **125 → 188** growth is the anchor track. Measure it
  at every pre-#524 point.
- **Wavefront `stage_shade_bucketed_n7` regs** — the surviving track (221 today).
  Present once the N+7 bucketed shade lands; measure it wherever it exists.

Because both kernels inline the same shared device shading functions
(`gpu_material_sample_spectral`, spectral tables, light-energy/wattage
derivation, etc.), the two tracks should **co-move**. A commit that jumps the MW
track and the WF-shade track together localizes the shared-code regression; a
commit that moves only one localizes a kernel-specific cost. Do not assume one
cause.

## 2. First-class recorded variables (confounds — pin and log at EVERY point)

1. **nvcc / CUDA toolkit version.** Live confound found in Phase 1 §6:
   `scripts/build/build_cuda_worktree.bat` **hardcodes CUDA v12.6** while
   `CUDA_PATH`/`PATH` and `configure_and_build.bat` resolve to **v12.8**.
   Register allocation is compiler-version sensitive, so a toolkit mismatch would
   forge a phantom register jump. **Build every bisect point with the SAME
   toolkit — v12.8 in the main checkout via `configure_and_build.bat`**, matching
   the toolkit under which Phase 1's baseline (125/188) and current (221) numbers
   were measured. Record `nvcc --version` per point; discard any point built with
   a different toolkit.
2. **tables-loaded checksum** (signal 4) — pkg153's hardened-protocol mandate; a
   ratio change with tables absent is a load bug, not a transport regression.
3. **Build config = Release**, seed, spp=64, max-depth=8, scene set, resolution
   256² — pinned identical to Phase 1.
4. **GPU thermal/lock state** for the ms leg only (signal 2): median-of-5, cool
   start, GPU lock held — per the pkg155/pkg55-C7 timing discipline. Signals 1,
   3, 4 are noise-free and do not need thermal control.

## 3. Window and points

Window: **#481 → #524**. 4–6 points. Bisect **on signal 1 (regs) first** — it is
compile-only and deterministic, so you can localize the occupancy cliff cheaply,
then spend GPU render time only at the candidate origin commits to capture
signals 2–4.

Suspect anchors (union of both specs' lists):

| Commit / PR | pkg155 relevance (regs/perf) | pkg153 relevance (R-drift) |
|---|---|---|
| #481 spectral-table extraction | reg-growth suspect (shared spectral eval) | suspect 1B (spectral eval); not excluded for the residual |
| #484 MIS instrumentation | reg-growth (per-thread state) | — |
| #486 naive MW / non-visible bands | reg-growth | — |
| #489 / #500 light-energy + wattage→radiance | reg-growth (shading) | **suspect 1A** — emitter-linked (≈4.6pp of the 5.7pp R drift, C7 discriminator) |
| #490 TLAS | reg-growth (traversal) | — |
| #494 photon hooks | reg-growth | — |
| #497 / #503 C6 ReSTIR | — | env/world-scene suspect |
| #513–#517 round | reg-growth | env-scene suspect |
| #515 firefly clamp | reg-growth (shade) | — |
| #518 Disney closure-graph routing | **reg-growth (shade-heavy)** | — |
| #519 rough-transmission multiscatter LUTs | reg-growth (shade) | — |
| a7f09d1^ / 41101a5^ | — | **pkg153's decisive bisect step** — fold in |
| #523 pkg152 compensation-table mirror | — | **COMPOUNDING ANCHOR ONLY, never an origin candidate** — moved R +3.8pp post-hoc (pkg153 rule) |

## 4. Discipline

1. **Bisect on regs first** (signal 1, compile-only) to localize the occupancy
   cliff — sharpest, cheapest, no GPU render, no timing noise.
2. At each candidate origin commit, **then** capture signals 2–4 (one render pass
   per point) to confirm the reg jump tracks the ms jump (pkg155) and to place the
   R-ratio jump (pkg153).
3. **Do not assume one shared cause.** pkg155 and pkg153 may converge on the same
   spectral-eval-arc origin commit or split; record a per-signal verdict. The
   photon-caustic negative-SSIM flake is a distinct cause (pkg153) and is out of
   scope for this window bisect.
4. **#523 stays a compounding anchor, never an origin** (pkg153 rule).
5. Every claim needs hardware evidence for signals 2–3; CI is blind (memory
   `ci_has_no_gpu_runtime_blindspot`).

## 5. Outputs

- **One attribution table per signal**, cross-referenced by commit, with the
  recorded confounds (toolkit, checksum) per row.
- **pkg155:** the recovery plan against the **≤128 regs/thread** shade target
  (Phase 1 §5 levers: `__launch_bounds__` — noting shade's 256-thr/1792-block
  geometry differs from the other stages' 512/256, so evaluate against that;
  per-material-class shade split; live-state audit; scene-gated feature
  branches). Separately investigate the shade dispersion tail (Phase 1 §4) — a
  divergence lever independent of occupancy.
- **pkg153:** a disposition per gate — re-pin with workstation evidence (if a
  stale machine-pin is convicted) **or** a targeted fix spec (if a real
  regression is convicted), leaving the gate red-and-owned. Never relax to green
  without conviction (pkg153 contract).

## 6. Owner-approval item — do NOT change tonight

Align `scripts/build/build_cuda_worktree.bat` from hardcoded CUDA **v12.6** to
**v12.8** to match `CUDA_PATH`/`PATH` and `configure_and_build.bat`. Deferred by
the team-lead deliberately: swapping toolkits mid-investigation would confound
the register measurements this whole protocol depends on. Flag for owner as a
standalone change to land AFTER the bisect completes.

## References

- pkg155 Phase 1: `.astroray_plan/docs/pkg155-phase1-profile-findings.md`
- pkg155 spec: `.astroray_plan/packages/pkg155-gpu-absolute-slowdown-investigation.md`
- pkg153 spec: `.astroray_plan/packages/pkg153-wavefront-diff-env-gates-disposition.md`
- Baseline of record: `benchmarks/wavefront/baseline.json` (2026-05-17 @ `1a3c159`)
- Final-megakernel pin: `benchmarks/wavefront/megakernel_final_2026-07-25.json` (@ `e0185c8`)
