# pkg237 — HDRI background CPU/GPU SSIM diagnosis

**Pillar:** 5
**Track:** A
**Status:** done — replaced the SSIM gate with the per-channel mean-ratio gate in `tests/test_world_hdri_parity.py::test_gpu_cpu_mean_ratio_hdri` (renamed from `test_gpu_cpu_ssim_hdri`); measured on RTX 5070 Ti (build_cuda .pyd 07:54 2026-09-08, HEAD 32c39836, no C++/CUDA changes since): GPU/CPU per-channel mean ratios R=1.0253, G=1.0400, B=0.9783 (all within +-5%), SSIM diagnostic 0.9622-0.9637 (printed, not asserted); PR #754
**Estimated effort:** TBD
**Depends on:** none

---

## Goal

Before: the HDRI background CPU/GPU SSIM divergence is undiagnosed — plausible
hypotheses are not separated from established causes and the actual CPU/GPU
environment consumers are untraced. After: the HDRI background CPU/GPU
divergence is diagnosed before any fix or gate change, with linear arrays and
matched fixed seeds/config/imported-native-artifact metadata preserved across
captures; environment direction mapping/orientation, spectral
sampling/accumulation, image filtering, and test normalization and statistical
validity each inspected independently; component experiments isolated; and
filtering evidence coordinated with pkg234 only if relevant, without assuming
dependency or cause.

---

## Context

This package serves Pillar 5 (CPU/GPU parity) and is a diagnosis of existing
behavior. This follow-up does not change owner queue priority; Pillar 4 remains
PAUSED.

---

## Evidence

- `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri` renders an
  environment-only scene (no geometry, no shader VM) at 8192 spp: feature SSIM
  0.7690514 vs threshold 0.97, freshly built root/main SSIM 0.77432567.
- The current test normalizes each image by its own maximum via
  `arr / max(1.0, float(arr.max()))` before SSIM, so metric validity needs
  examination.
- The mismatch also reproduces on baseline; pkg230 causation is not established.

### Diagnosis 2026-09-07 (fix/pkg237-238-diagnosis, PR #731)


Full detail: `.astroray_plan/docs/pkg237-238-diagnosis-2026-09-07.md`.

ROOT CAUSE (not an engine parity bug — reproduced with NO GPU). Two compounding
test-methodology defects (pkg73 pattern):

- Defect A (dominant): `render()` defaults `useAdaptiveSampling=true`. The per-pixel
  adaptive stop uses a colour-blind scalar metric (lum = X+Y+Z, raytracer.h:4072). Blue's
  RGB->spectrum upsampled reflectances are the spikiest, so blue carries ~3x the residual
  chromatic MC variance the scalar metric implies. Pixels stop with a large blue residual
  that does NOT fall with the sample budget. CPU and GPU draw independent RNG streams, so
  their residual blue-noise patterns decorrelate and SSIM never reaches 0.97.
  Distinguishing evidence: two INDEPENDENT CPU streams (proxy for CPU-vs-GPU) at 8192 spp,
  lin()=arr/max normalization + SSIM: adaptive=True -> 0.677 (reproduces the 0.769 failure);
  adaptive=False -> 0.962. Cross-seed per-pixel diff-std: adaptive OFF falls as clean
  sqrt(N) in all channels; adaptive ON stalls (R~0.015, B~0.05).

- Defect B (keeps it red even after A): the metric normalizes each image by its OWN max
  (`arr / max(1, arr.max())`). The green firefly (value 50) integrates to slightly different
  per-image maxima on independent streams (0.579 vs 0.582 even converged), scaling the two
  legs differently; combined with residual blue chromatic variance this caps converged
  independent-stream SSIM at ~0.96, still under the 0.97 pin. Distinguishing test: common-
  exposure (shared divisor) instead of per-image max should lift converged SSIM.

Proposed fix (routed to package-implementer, needs independent review + owner sign-off on the
metric change): the parity test must (A) disable adaptive sampling so 8192 spp converges both
legs, and (B) use a common exposure, not per-image max. Neither relaxes the threshold; both
make the gate measure converged parity as its own docstring intends. NOT the same defect as
PR #729 (absolute brightness vs Cycles) — see diagnosis doc.

---

## Reference

- Evidence files: feature `test_results/pkg230-p2/full-suite.log` and
  `baseline-full-suite-failures.log`.

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

None.

### Key design decisions

- Detailed architect review fixes the evidence-gathering scope first; only then
  a justified minimal fix or a scientifically supported gate proposal.

---

## Acceptance criteria

- [x] Reproducible matched captures preserve raw linear data + metadata (fixed
      seeds 1234/5678, env-only scene, apply_gamma=False, 8192 spp).
- [x] Independent oracle localizes the disagreement: two independent CPU streams
      (no GPU) reproduce the failure (0.677 adaptive-on) and the recovery (0.962
      adaptive-off), proving it is the colour-blind adaptive stop, not parity.
- [x] Common-exposure comparison accompanies the score: shared divisor vs
      per-image max both land ~0.962 in the CPU proxy (0.5% max delta), with
      seed-repeatable numbers recorded.
- [x] Saved representative visuals qualitatively reviewed by Astra/Claude — N/A:
      the gate change is a metric/assertion swap only (no renderer, camera, or
      HDRI fixture change), so there is no new visual output to review; the
      rendered images are byte-identical to the pre-change legs.
- [x] No geometry/VM confounders: env-only scene, no meshes, no shader VM.
- [x] Engine unchanged (test-method change only); no ABI/native surface touched.
- [x] GPU lock held (job pkg237); single worktree; regression tests run.
      2026-09-08: gate closed with the per-channel mean-ratio metric (SSIM kept
      as a diagnostic print, 0.97 pin retired per owner decision). Measured
      R=1.0253 (2.53%), G=1.0400 (4.00%), B=0.9783 (2.17%) — all within the
      +-5% band, test PASSES. CPU two-stream proxy (seeds 1234 vs 5678, same
      scene/spp, both CPU) measured |ratio-1| = 0.02% (R), 0.14% (G), 0.04% (B)
      — i.e. CPU-vs-GPU deviates ~15-200x more than the CPU-vs-CPU RNG-noise
      floor on every channel, far past the ~3x flag in the lane brief. This is
      reported as an OPEN FINDING below (not fixed in this PR — out of scope,
      no engine changes): the mean-level CPU/GPU gap looks larger than pure
      independent-stream noise would predict, though it stays inside the +-5%
      band the north-star gate (c) already accepts.

---

## Non-goals

- Risk: per-image max normalization can manufacture agreement or loss unrelated
  to rendering.
- Metric validity is part of the diagnosis, not a pretext for relaxing a gate.
- No arbitrary SSIM threshold relaxation.
- No transport/VM rewrite.
- No HDRI-filter root-cause claim before evidence.
- Do not assert a root cause or lower the threshold as a fix.
- No owner queue priority change.
- No Pillar 4 work.

---

## Progress

- [x] 2026-09-08 afternoon — Sonnet lane (`fix/pkg237-mean-ratio-gate`): reworked
      `test_gpu_cpu_ssim_hdri` -> `test_gpu_cpu_mean_ratio_hdri` in
      `tests/test_world_hdri_parity.py`. Kept setup identical (env-only scene,
      64x64, 8192 spp, `set_adaptive_sampling(False)` both legs, linear output
      `apply_gamma=False`, same HDRI fixture/rotation/tint). New assertion: for
      each of R/G/B, `abs(gpu[...,c].mean()/cpu[...,c].mean() - 1) <= 0.05`.
      SSIM (shared-exposure normalisation, unchanged) is computed and printed
      as `[pkg237] SSIM diagnostic ...`, printing "n/a" if scikit-image is
      missing so the mean-ratio gate always runs. Removed the
      `xfail(strict=True)` marker pkg258 had added. Grepped the repo for the
      old name `test_gpu_cpu_ssim_hdri`: no hits in `.github/`, `scripts/`, or
      any CI selection list; the remaining hits are dated historical evidence
      records (pkg85-D "done" 2026-05-14, pkg55, pkg230b delivery evidence,
      pkg85 test-harness notes) describing past runs under the old name, left
      untouched as historical record; `next-session-prompt-2026-09-08.md`
      (this task's own handoff prompt) also left untouched.
      MEASURED on RTX 5070 Ti, `build_cuda/astroray.cp313-win_amd64.pyd` built
      2026-09-08 07:54 from main HEAD `32c39836` (verified no `.cpp/.cu/.h`
      commits landed after that build time, so it is current; branch itself
      changes zero C++/CUDA — `git diff origin/main --stat` shows only the
      test file):
      `python scripts/dev/run_tests.py --build-dir .../build_cuda tests/test_world_hdri_parity.py -k mean_ratio -s -v`
      -> 1 passed. `[pkg237] SSIM diagnostic 0.9622-0.9637` across two runs
      (not asserted). Per-channel mean ratios: R 1.0253 (cpu 0.457456, gpu
      0.469012), G 1.0400 (cpu 0.014391, gpu 0.014967), B 0.9783 (cpu
      0.475410, gpu 0.465085) — all within +-5%. Full file
      `tests/test_world_hdri_parity.py` (all 3 tests): 3 passed both times.
      CPU two-stream proxy (seeds 1234 vs 5678, identical scene/spp, both
      CPU): R ratio 1.0002 (|.-1|=0.02%), G ratio 0.9986 (0.14%), B ratio
      1.0004 (0.04%) — i.e. two independent CPU RNG streams agree on the mean
      to <=0.14%, while CPU-vs-GPU disagrees by 2.17-4.00% — roughly 15-200x
      larger than the RNG-noise floor on every channel. Per the lane brief's
      ~3x flag this is reported as an OPEN FINDING (see acceptance criteria):
      the gap still clears the +-5% band so the assertion is NOT tightened or
      pinned further in this PR, but the size of the gap relative to the
      noise floor suggests it may be more than pure independent-stream
      variance (e.g. a small systematic CPU/GPU env-sampling bias) and is
      worth a follow-up look — no engine changes were made here, scope was
      test-method only per the brief's "Do not" list.
      Evidence logs: `test_results/2026-09-08-pkg237/gpu_gate_run_with_ratios.log`,
      `test_results/2026-09-08-pkg237/gpu_gate_final.log`,
      `test_results/2026-09-08-pkg237/cpu_two_stream_proxy.log` (all
      gitignored, not committed).
      `python scripts/project_index.py lint .astroray_plan/packages/pkg237-hdri-cpu-gpu-ssim-diagnosis.md` — TBD, run before PR.

- [ ] 2026-09-08 morning — OWNER DECISION: close the gate with the converged per-channel
      mean-ratio (the metric `benchmarks/blender_parity` already uses); keep SSIM as a
      diagnostic print, retire the 0.97 pin (independent-stream floor 0.962–0.963). Next:
      Sonnet lane edits the test, measures on the RTX, flips to done.

- [x] 2026-09-07 evening — owner chose option (c) for the 0.9628 residual:
      **replace the single-firefly synthetic HDRI with a firefly-free parity
      scene** in `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri`
      (keep the gradient so rotation is still detectable; cap the bright
      spot at a value that does not dominate the per-pixel variance, e.g.
      ≤ 4× the gradient peak, or spread it over a 3×3 patch), keep adaptive
      off + shared exposure, keep the 0.97 pin, and record the new measured
      CPU-vs-GPU SSIM on the RTX 5070 Ti. The rotation/tint tests keep
      their own HDRI. Flip to `done` when the GPU gate is green.
      IMPLEMENTED: added `_write_firefly_free_hdri` + a dedicated
      `ssim_hdri_path` module-scope fixture (same blue/red gradient, bright
      spot capped at 4x the gradient peak — 4.0 instead of the old firefly's
      50.0); `test_gpu_cpu_ssim_hdri` now takes `ssim_hdri_path` instead of
      the shared `hdri_path`; the rotation/tint tests are untouched and still
      use the original firefly-at-50 `hdri_path` fixture.
      LEAD DECISION 2026-09-08: the fixture change is measured as neutral
      (below), so it was NOT merged — PR #742 carries only this record;
      `tests/test_world_hdri_parity.py` is unchanged on main.
- [x] 2026-09-08 — MEASURED on RTX 5070 Ti (main-checkout build_cuda .pyd,
      built from HEAD fe535b6a, mtime after HEAD, canary green): actual
      CPU-vs-GPU gate on the NEW firefly-free (capped-at-4x) fixture, 64x64,
      8192 spp, adaptive off + shared exposure: **SSIM 0.9625** — still
      **0.0075 short of 0.97**, essentially unchanged from the pre-fix
      0.9628 (firefly-at-50) and the CPU-proxy 0.9618.
      CPU two-stream proxy (seeds 1234 vs 5678, same firefly-free scene,
      independent streams == the CPU-vs-GPU situation): **SSIM 0.96182245**
      (shared-exposure AND per-image-max identical to 8 decimal places;
      maxA=0.5793, maxB=0.5856 — barely different from the OLD firefly-at-50
      proxy's maxA=0.579/maxB=0.582).
      ALTERNATIVE SHAPING TRIED (per instruction, once): spread the same
      4.0 peak over a 3x3 patch instead of one capped pixel. CPU two-stream
      proxy result: **SSIM 0.96182245** — bit-identical to the capped-peak
      result to 8 significant figures, and maxA/maxB also unchanged
      (0.5793/0.5856). ROOT CAUSE OF THE NULL RESULT: with NO geometry in
      this env-only scene, every pixel's radiance is exactly
      `eval_env_spectral` at that pixel's lookup direction, bilinearly
      interpolated across the 32x16 texel grid. A camera pixel whose lookup
      direction lands near the bright-spot's texel column samples a value
      bounded by the texel's OWN value (4.0) regardless of whether that
      value occupies 1 texel or a 3x3 block of equal-valued texels —
      bilinear interpolation between equal neighbours returns that same
      value either way, so neither shaping choice changes the rendered
      image's peak or its per-pixel statistics. The firefly (at 50 OR at 4)
      was never actually driving the measured maxA/maxB or the SSIM
      residual at this resolution — the 0.96-0.97 gap is the GENUINE
      independent-RNG-stream Monte Carlo noise floor for this scene at
      8192 spp (SSIM's windowed local-variance metric comparing two
      decorrelated-but-converged noise fields on a spatial gradient), not a
      firefly artifact. CONCLUSION: the owner's firefly hypothesis is
      empirically falsified by this measurement — status stays `open` per
      the spec's non-goals (no threshold relaxation, no unproven root-cause
      claim). Closing pkg237 needs a decision outside this lane's scope:
      accept a re-pinned threshold at the measured ~0.96 independent-stream
      floor, raise spp further, add an explicit denoise step before SSIM, or
      change the metric (e.g. per-channel mean-ratio, already used
      elsewhere per memory `ssim-wrong-gate-for-independent-rng`).
- [x] 2026-09-07 08:30 — owner approved the test-method fix (adaptive sampling
      off + shared exposure); threshold 0.97 unchanged.
- [x] 2026-09-07 — CPU two-stream proxy re-confirmed on the fix branch module
      (build_cuda .pyd 05:40, main+pkg253). Env-only scene, 8192 spp, seeds
      1234 vs 5678 (independent streams == the CPU-vs-GPU situation):
      - adaptive=True : SSIM 0.6768 (reproduces the 0.769 failure signature)
      - adaptive=False: SSIM 0.9618 per-image-max AND 0.9618 shared-exposure
        (maxA=0.5793, maxB=0.5856; shared divisor = max of both).
      Turning adaptive off restores clean sqrt(N) convergence (0.677 -> 0.962),
      confirming Defect A; the two per-image maxima differ only 0.5% so SSIM's
      local normalization makes the shared-exposure lift marginal in the proxy,
      but shared exposure is the methodologically correct divisor (Defect B).
- [x] 2026-09-07 — implemented the approved test-method fix in
      `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri`:
      `set_adaptive_sampling(False)` on both legs + a single shared exposure
      divisor. Threshold left at 0.97.
- [ ] 2026-09-07 — ACTUAL CPU-vs-GPU gate on RTX 5070 Ti (build_cuda .pyd 05:40),
      64x64, 8192 spp, adaptive off + shared exposure: SSIM **0.9628** vs the
      unchanged 0.97 pin. Up from the 0.769 pre-fix failure, but still **0.007
      short**. This is the expected independent-RNG chromatic-noise floor for
      this single-firefly env scene: the CPU two-stream proxy (also independent
      streams) lands at 0.9618 under the identical converged conditions, so the
      residual is the scene's noise floor, NOT a parity defect and NOT a
      remaining engine bug. Per owner instruction the 0.97 threshold was NOT
      relaxed; residual recorded and stopped. STATUS stays `open` — closing
      pkg237 needs an owner decision outside this lane's approved scope (accept
      a re-pinned threshold at the measured independent-stream floor, raise spp
      / add a denoise step, or use a firefly-free parity scene).
- [x] 2026-09-07 — root-cause diagnosis landed (PR #731); fix is a test-method change pending owner review.

---

## Lessons

- SSIM is the wrong gate for two independently-seeded MC renderers: its
  windowed local-structure comparison floors at ~0.96 on decorrelated-but-
  converged noise even when the underlying per-channel means agree. The
  per-channel mean ratio (already used in `benchmarks/blender_parity` and the
  cycles-parity thin-film sweep) is the metric that actually reflects
  converged CPU/GPU agreement for an unbiased MC estimator and is not
  confounded by independent RNG streams (memory
  `ssim-wrong-gate-for-independent-rng`).
