# pkg131 — Zero-knob adaptive sampling (Cycles `adaptive_sampling.h` model, wavefront-integrated)

**Pillar:** 3 (light transport / render efficiency)
**Track:** A (CPU-first convergence-check + scheduler on CI; wavefront active-pixel compaction leg verified on RTX)
**Codex-paste-ready:** no (one film convergence kernel + scheduler change + wavefront compaction integration + addon UI *removal* — architectural, needs the wavefront's compaction owner in the loop)
**Status:** UNBLOCKED — the hard prerequisite (a progressive/low-discrepancy RNG with the Sobol/PMJ prefix property) is now MET by **pkg224** (`packages/pkg224-progressive-sampler.md`, landed): an opt-in hash-Owen-scrambled Sobol' sampler at every GPU wavefront draw, selected by `renderer.set_use_progressive_sampler(True)` → the `__constant__ c_wfSamplerMode` published in `cuda_wavefront_render` → `WavefrontRNG::Uniform()`. Verified prefix property + faster-than-1/√N convergence (`tests/test_pkg224_progressive_sobol.py`). **To implement pkg131:** turn the progressive sampler ON for the wavefront, then vary per-pixel sample counts against the convergence estimator — the progressive prefix property guarantees every partial sample count is well-distributed, so early stopping in easy regions no longer degrades noise. pkg224 is GPU-only (CPU keeps `std::mt19937`); pkg131's wavefront leg is the natural first target. Spec-filing PR #492; memory `pkg131-blocked-on-progressive-sampler`.
**Estimated effort:** M (2–3 sessions per the research doc — one film kernel, scheduler change, addon UI removal rather than addition)
**Depends on:** progressive-in-samples RNG (pkg92's sequence must have the PMJ/Sobol prefix property — a hard prerequisite; verify before implementing). Composes with pkg55 Phase C (the wavefront already owns active-pixel compaction — the convergence check feeds it). OIDN pairing is fine (Cycles ships the same combination).

---

## Goal

**Before:** Astroray renders a fixed `samples = N` per pixel. Converged regions
keep drawing samples they don't need while noisy regions stay noisy at the same
budget — the classic uniform-sampling waste, worst on the 8 GB travel laptop where
every wasted sample costs wall-clock the hardware can't spare.

**After:** Port Cycles' **zero-knob** adaptive sampler
(`kernel/film/adaptive_sampling.h`, Apache-2.0): per-pixel noise is estimated from
a half-sample auxiliary buffer against the Dammertz 2010 brightness-relative error
metric; pixels below an **auto-derived** threshold stop; the unconverged mask is
dilated so neighborhoods sample together; a minimum-sample floor and a `max_samples`
safety cap replace the `samples = N` knob. Integrated into the wavefront: render in
waves → convergence-check kernel → compact the active-pixel list (the wavefront
already owns compaction) → stop when all pixels converge or the cap hits.

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-other-engines-research.md` §5.

- **Error metric (Dammertz §2.1, as Cycles implements it):**
  `error = (|I−A|₁) · (exposure/samples) / (0.0001 + error_normalize)` with
  `error_normalize = sqrt(intensity)` below 1.0 else `intensity` (brightness-relative
  noise); converged when `error < threshold`.
- **Auto threshold (the zero-knob mechanism):** Cycles' `threshold = 0` derives the
  noise threshold from the sample budget in `integrator/render_scheduler.cpp`. Port
  that derivation — that is what "no sampling knobs" means.
- **Dilated mask:** `film_adaptive_sampling_filter_x/_y()` two-pass box filter over
  the unconverged mask so neighborhoods keep sampling together (avoids splotchy
  early-out boundaries).
- **Wavefront integration:** the convergence check writes the active-pixel mask; the
  wavefront's existing compaction (`stageRegenKernel` / alive-queue compaction,
  `src/gpu/wavefront/stage_advance.cu`) consumes it to retire converged pixels.

**8 GB / architecture constraints (from the research doc):** (a) RNG must be
progressive-in-samples (pkg92 prefix property); (b) the half-buffer must be **scalar
luminance**, not full spectral, to avoid doubling framebuffer memory on 8 GB;
(c) OIDN interacts fine; (d) the telescope noise pass (pkg51) applies after and is
unaffected.

---

## Implementation plan

- **A. Convergence-check film kernel (CPU-first).** Scalar-luminance half-buffer +
  Dammertz error metric + per-pixel converged flag. Mirror
  `film_adaptive_sampling_convergence_check()`.
- **B. Auto-threshold scheduler.** Port the `threshold = 0` sample-budget derivation
  + minimum-sample floor + `max_samples` cap; check every N samples.
- **C. Wavefront integration + UI removal.** Wire the mask into active-pixel
  compaction; remove the `samples = N` addon knob, expose `max_samples` + (optional)
  a noise-threshold override defaulted to auto.

---

## Acceptance criteria

- [ ] Convergence-check kernel (scalar-luminance half-buffer, Dammertz metric) on
      CPU and wavefront; converged mask dilated (filter_x/_y).
- [ ] Auto threshold derived from the sample budget (`threshold = 0` semantics) +
      minimum-sample floor + `max_samples` cap; no per-pixel sample knob remains.
- [ ] Wavefront retires converged pixels via existing compaction; equal-quality
      image reached in fewer total samples than fixed-N on a noisy reference scene
      (measured speedup reported).
- [ ] Half-buffer is scalar luminance (framebuffer memory not doubled) — verified on
      the 8 GB config.
- [ ] No-regression: OIDN and the pkg51 telescope pass still work; CPU↔GPU
      wavefront-diff parity holds.

---

## Non-goals

- **Not a new sampler.** Uses the existing (pkg92) sequence; only requires its
  prefix property. If pkg92's sequence lacks it, that is a blocking prerequisite,
  not in-scope work here.
- **Not variance-estimator infrastructure.** pbrt-v4's `VarianceEstimator` (Welford)
  is the alternative if half-buffers prove insufficient — note it, don't build both.
- **Not the denoiser.** OIDN is orthogonal; this only ensures they compose.

---

## Algorithm sourcing (CLAUDE.md §6)

- **Cycles** `github.com/blender/cycles` — **Apache-2.0 (verified)**.
  `src/kernel/film/adaptive_sampling.h` (`film_adaptive_sampling_convergence_check`,
  `_filter_x/_y` dilation); `src/integrator/render_scheduler.cpp` (check cadence,
  min-sample floor, `threshold = 0` auto-derivation).
- **Dammertz, Hanika, Keller, Lensch**, "A Hierarchical Automatic Stopping Condition
  for Monte Carlo Global Illumination", WSCG 2010 — the per-pixel error metric.
- **Christensen et al.**, "RenderMan: An Advanced Path-Tracing Architecture", ACM
  TOG 37(3), 2018, DOI 10.1145/3182162 — odd/even half-buffer variance (Cycles'
  stated inspiration).
- **Christensen, Kensler, Kilpatrick**, "Progressive Multi-Jittered Sample
  Sequences", CGF 37(4)/EGSR 2018 — the prefix property the RNG must satisfy.
- **pbrt-v4** `github.com/mmp/pbrt-v4` — Apache-2.0 (verified). `VarianceEstimator`
  (`src/pbrt/util/math.h`) — Welford online variance, the fallback infra only.
- **Research doc:** `.astroray_plan/docs/2026-07-other-engines-research.md` §5 +
  adoption rank 3.

---

## Provenance

Filed from the **other-engines technique sweep (2026-07-19)**
(`.astroray_plan/docs/2026-07-other-engines-research.md` §5, adoption rank 3: "big
render-time win on 8 GB hardware"). Owner goal: kill wasted samples on the
memory-constrained travel laptop and remove a user-facing sampling knob rather than
add one.

---

## Progress

- [x] **Shared core** `include/astroray/sampling/adaptive_sampling.h` — cited
      `__host__ __device__` Dammertz metric (scalar-luminance half-buffer), zero-knob
      auto-threshold + min-sample floor derivation, and the two-pass 3×3 mask
      dilation. Verified byte-exact against Cycles values (research note
      `.astroray_plan/docs/pkg131-adaptive-sampling-autothreshold-research.md`);
      6 host unit tests (`tests/test_pkg131_adaptive_sampling.py`). (2026-08-30)
- [x] A (CPU) + B — CPU per-pixel leg: `Renderer::render` now stops each pixel via
      the shared core instead of the old hand-rolled coefficient-of-variation
      early-out; `maxSamples` is the auto-threshold budget. Verified: low-budget
      bit-identical no-op + high-budget unbiased/bounded
      (`tests/test_pkg131_adaptive_cpu_render.py`). (2026-08-30)
- [ ] C (GPU) — wavefront **compacted active-pixel round** on top of the existing
      flat work pool (`stageRegenKernel` indexes `activePixels[w % numActive]`,
      per-pixel sample counter, per-pixel final divide; convergence-check kernel
      between rounds). Additive, byte-identical when off, respects the flat-pool
      perf design. Design in the research note. NOT a wave-based rewrite. HW-verify
      on RTX (CI has no GPU).
- [ ] Sample-count AOV (report measured speedup) + addon UI: remove the `samples=N`
      knob, expose `max_samples` + optional auto-defaulted noise-threshold override.

---

## Lessons

*(Fill in after the package is done.)*
