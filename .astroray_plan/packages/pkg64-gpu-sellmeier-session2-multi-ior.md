# pkg64-gpu-sellmeier-session2 — Per-wavelength multi-IOR GPU refraction

**Pillar:** 1
**Track:** A
**Status:** Session 2 implemented 2026-05-28 (PR pending merge); SSIM/PSNR gates re-spec'd, energy gate green
**Estimated effort:** 1–2 weeks
**Depends on:** pkg64-gpu-sellmeier-upload (PR #354, merged Round 14 2026-05-24, hero-only) + pkg55-B' Session N+4 part 1+2 (PRs #355+#356, NEE infrastructure on GPU)
**Reference research:** Sellmeier 1871 (public domain); Cycles `intern/cycles/kernel/svm/closure_principled.h` per-wavelength refraction (Apache-2.0); PBRT-v4 `src/pbrt/bxdfs.h` `DielectricBxDF::Sample_f` multi-wavelength branch (Apache-2.0); Hero-wavelength algorithm — Wilkie et al. 2014 "Hero Wavelength Spectral Sampling" (EGSR 2014), reference for the splitting strategy.

---

## Why this package exists

pkg64-gpu-sellmeier-upload (Session 1, shipped PR #354) added Sellmeier dispersion coefficient upload + hero-channel-only refraction to the GPU. The Session 1 RTX HW verify on 2026-05-24 PASSED the receiver-energy gate (1.17× ≥ 1.10×) but DEFERRED two acceptance gates:

| Gate | Threshold | Session 1 measured | Reason for deferral |
|------|-----------|--------------------|---------------------|
| PSNR floor delta | ≥ −0.5 dB | −2.13 dB | Hero-only GPU lacks chromatic spread → per-pixel error dominated by spatial caustic divergence, not numerical regression |
| GPU↔CPU SSIM parity | ≥ 0.97 | 0.523 | Same root cause: GPU caustic is concentrated at a single IOR's bend angle; CPU spreads across 4 wavelengths |

Both gates are physically meaningful and the spec author wanted to keep them. The Session 1 deferral was the right call (hero-only is a smaller scope than the spec implied), but the proper fix is to make GPU produce the same chromatic spread CPU does. That's this package.

---

## Goal

**Before (Session 1):** GPU dispersive dielectric refracts the entire path at `gpu_sellmeier_ior(coeffs, lambda[0])` — hero wavelength only. CPU spawns 4 wavelength samples per ray and refracts each at its own IOR, producing a 4-way chromatic spread that lands at distinct receiver pixels.

**After (Session 2):** Two options on the design axis; pick one in Phase 1:

### Option A — Per-wavelength split inside the dielectric kernel

When the GPU path hits a dispersive dielectric, the kernel splits into N refraction directions (N = number of sampled lambdas, typically 4). Each direction is traced separately; throughput is divided by N (or by importance-sampled weight). This mirrors CPU per-wavelength sampling exactly.

- **Pro:** Bit-equal to CPU at the wavelength-sampling level; SSIM should approach 0.97.
- **Pro:** Same number of total samples consumed by the path (no MIS bookkeeping change).
- **Con:** N rays per hit on a dispersive dielectric — branching factor up to 4× on caustic paths. Could blow up frame time on prism-heavy scenes.
- **Con:** Wavefront kernel becomes variadic in work-per-thread; complicates the SoA model.

### Option B — Hero-wavelength MIS with chromatic spread

Use the Wilkie et al. 2014 hero-wavelength algorithm: at each dispersive-dielectric hit, pick one wavelength as the hero, refract at its IOR, but ALSO compute the MIS weight against the other wavelengths' implicit pdfs. Throughput is the hero's spectral contribution weighted by the MIS combination.

- **Pro:** Stays single-ray per hit — wavefront branching unchanged.
- **Pro:** Cycles uses this pattern (`closure_principled.h` hero_wavelength branch).
- **Con:** Asymptotically approaches CPU per-wavelength only at high SPP; PSNR/SSIM may stay below the gates at 256 SPP.
- **Con:** Extra per-hit math: 4 IOR evaluations + 4 BSDF pdf evaluations for the MIS.

**Recommended Phase 1 decision:** Option B (hero-wavelength MIS), with a documented fallback to Option A if SSIM doesn't reach 0.97 at the 256-SPP gate. Justification: Cycles uses B, and the integrator integration is lighter — the spectral kernel already evaluates per-lambda pdfs for emission, so the BSDF MIS extension is a smaller delta.

**Owner decision (2026-05-24, Round 14 close-round):** confirmed — start with Option B, accept the risk that it may not clear the 0.97 SSIM gate at 256 SPP. If Option B converges to ~0.93–0.95 and stalls, fall back to Option A in a follow-up session rather than committing to A upfront. This trades a possible second deferral for the simpler (and Cycles-aligned) implementation path. Architect surfaced this as the highest-value Session 2 open question; owner adjudicated.

---

## Specification

### 1. Phase 1 — Pick the algorithm; file research notes

Save `.astroray_plan/docs/pkg64-gpu-session2-research.md` with:
- Wilkie 2014 paper citation + the exact MIS formula (eq 5).
- Cycles `closure_principled.h` line range that implements hero_wavelength MIS.
- Decision: Option A or Option B, with the receiver-energy + caustic-branching tradeoff explained.
- Acceptance plan: how the chosen algorithm closes both deferred gates.

### 2. Phase 2 — Implement the chosen algorithm

If Option B (recommended):
- Extend `gpu_dielectric_sample_spectral()` in `include/astroray/gpu_materials.h` to compute MIS weights across `lambdas[0..3]` when `mat.isDispersive`.
- Each lambda evaluates its own `gpu_sellmeier_ior(mat.dispersion, lambdas.lambda[i])`.
- Compute per-lambda BSDF pdf at the hero's sampled direction.
- Combine via power heuristic (matching Cycles' `power_heuristic`).
- Throughput update: hero's spectral contribution × MIS weight.

If Option A:
- Add a `dispersion_split` flag to the wavefront pipeline.
- At a dispersive-dielectric hit, the path spawns 4 child paths (one per lambda); each gets `throughput/4` and the appropriate per-lambda IOR.
- The wavefront SoA needs to handle the spawn (probably via the existing `path_alive` mask + a compaction pass).

### 3. Phase 3 — Re-enable the deferred gates

In the Sellmeier worktree's amended tests, remove the `@pytest.mark.xfail(strict=False)` decorators from:
- `tests/test_pkg64_gpu_cpu_parity.py::test_pkg64_gpu_cpu_parity_ssim`
- `tests/test_pkg64_gpu_phase3_default_integrator.py::test_pkg64_gpu_phase3_prism_psnr_floor`

Re-run on RTX. Both should now pass:
- PSNR floor: ≥ −0.5 dB
- SSIM: ≥ 0.97

Update the `pkg64-gpu-sellmeier-upload.md` spec acceptance list to flip the deferred items back to live (un-strikethrough lines 112–113).

### 4. Phase 4 — Regression confirm

- Existing Session 1 BK7 unit test still passes (no change to `gpu_sellmeier_ior`).
- Existing scalar-IOR dielectric fast path bit-identical (the multi-IOR branch is `mat.isDispersive`-only).
- Receiver-energy gate still passes at 1.17× or better (more wavelengths → potentially more energy on receiver).
- No regression in CPU↔GPU `test_pkg55_cuda_threshold_gate` (Session N+3+N+4 stages).

---

## Tests

- **Existing tests (must continue to pass):** `test_gpu_sellmeier_ior.py`, `test_pkg64_gpu_phase3_prism_receiver_energy`, `test_pkg64_gpu_phase3_no_regression`, the full Session N+3+N+4 threshold gate.
- **Newly-enforced (formerly xfail) tests:** `test_pkg64_gpu_phase3_prism_psnr_floor`, `test_pkg64_gpu_cpu_parity_ssim`.
- **New tests (Phase 2):** unit-test the hero-wavelength MIS weight calculation against a hand-computed reference for a 4-wavelength symmetric case.

---

## Acceptance criteria

- [x] Phase 1 research notes filed at `.astroray_plan/docs/pkg64-gpu-session2-research.md` with chosen algorithm + Cycles/PBRT file:line + acceptance plan.
- [x] Phase 2 implementation lands; the chosen algorithm is cited in code comments (Wilkie 2014 + PBRT-v4 `SampledWavelengths::TerminateSecondary`).
- [x] `test_pkg64_gpu_cpu_parity_ssim` un-xfail'd and PASSES — **re-spec'd** (see Session 2 outcome below): SSIM 0.9277 ≥ 0.85 + ROI luminance-parity 1.30× in [0.5,2.0]. The original 0.97 was unreachable for independent MC streams (CPU-vs-CPU SSIM ≈ 0.53 at 256 spp).
- [x] `test_pkg64_gpu_phase3_prism_psnr_floor` un-xfail'd and PASSES at PSNR delta = +2.19 dB ≥ −0.5 dB on RTX.
- [x] No regression: 21 GPU-spectral tests pass (gpu_sellmeier_ior, gpu_multiwavelength, spectral_gpu_materials, sms_caustic_spectral, pkg64 phase2/phase3 no-regression, pkg55 CUDA threshold gate); 58 CPU spectral tests pass.
- [x] Visual inspection: GPU prism render shows chromatic spread (color speckles, ROI energy matched 1.08×); hero-wavelength now spans the full band.
- [ ] Spec amendment: `pkg64-gpu-sellmeier-upload.md` acceptance lines 112–113.

## Session 2 outcome (2026-05-28, supervised)

The Session 1 deferral framed this as "GPU needs per-wavelength chromatic spread."
The real root cause was a **GPU hero-wavelength distribution bug**:
`gpu_sampleBandWavelengths`/`gpu_sampleUniformWavelengths` confined `λ[0]` to the
first 1/N of the band (violet), while CPU `sampleUniform` (and the already-fixed
wavefront `stage_init.cu`) span the full band. The SMS caustic colorizes off
`λ[0]`, so the GPU caustic was violet (near-zero luminance) — which is why the
three 2026-05-28-morning attempts (all energy-normalization tweaks) failed on
both SSIM and energy. Fix: match the CPU/wavefront hero layout + mirror CPU's
`terminateSecondary` on dispersive refraction (the delta-collapse of Wilkie 2014
hero-MIS). Receiver-energy improved 1.17× → 1.38×.

Two gate-methodology findings (owner-adjudicated):
1. **SSIM ≥ 0.97 / PSNR ≥ −0.5 were unreachable as written.** CPU-vs-CPU SSIM
   (same engine, different seed) is only ~0.53 at 256 spp — the threshold
   exceeded the scene's own noise floor (`ssim-wrong-gate-for-independent-rng`).
   Re-spec'd to a noise-floor-aware SSIM ≥ 0.85 + ROI luminance-parity gate; the
   residual gap to 0.97 is the spec's pre-accepted "Option B stalls at 0.93–0.95"
   case (Option A = per-wavelength split remains a future option).
2. **The parity test had an integrator mismatch:** GPU ran
   `multiwavelength_path_tracer` (NEE off → dark floor) vs CPU `path_tracer`
   (NEE on → lit floor). Both route through the same megakernel; matching the
   integrator (GPU → `path_tracer`) fixed the floor and lifted SSIM 0.49 → 0.93
   and PSNR −3.9 → +2.2 dB. Receiver-energy keeps the no-NEE variant to isolate
   the caustic.

**Deferred (not needed):** the PBRT `pdf[0] /= N` compensation term (Astroray's
`terminateSecondary` omits it on both CPU and GPU). Energy already clears the
gate at 1.38× without it; adding it would change CPU caustic brightness and need
a CPU baseline re-bless. Filed in the research note as a future correctness item.

---

## Non-goals

- Cauchy or Conrady alternative dispersion forms. Sellmeier covers BK7 + the common Schott catalog scenes.
- Mesh-attached per-material dispersion overrides via the Blender addon. The pkg89 dedicated-materials path is the place; treat it as a future package.
- More than 4 wavelength samples per path. The wavefront SoA pins `lambdas[4]`; expanding that is a separate refactor.
- Adaptive wavelength sampling (e.g., concentrate samples on visible peaks of a fluorescent material). Hero or uniform; nothing fancier.

---

## References

- Sellmeier 1871 — Annalen der Physik 219(11):272-282 (public domain via age).
- Wilkie, Nawaz, Droske, Weidlich, Hanika 2014 — "Hero Wavelength Spectral Sampling" EGSR 2014. DOI 10.1111/cgf.12419. The hero-wavelength MIS algorithm.
- Cycles `intern/cycles/kernel/svm/closure_principled.h` (Apache-2.0) — hero_wavelength branch in the dielectric closure.
- PBRT-v4 `src/pbrt/bxdfs.h` `DielectricBxDF::Sample_f` (Apache-2.0) — alternative multi-wavelength dielectric reference.
- pkg64-gpu-sellmeier-upload spec (Session 1; PR #354). The "Deferred to Session 2" markers in its acceptance section name THIS package as the closer.
- pkg64-gpu-sellmeier-upload HW verify report 2026-05-24 — the measured PSNR −2.13 dB / SSIM 0.523 baseline this package needs to overcome.

---

## Filed by

team-lead overnight run, 2026-05-24, after PR #354 HW-verified at Session 1 acceptance with the SSIM + PSNR gates deferred. Filing this Session 2 spec now keeps the deferred-gate markers actionable for a Round 15+ pickup.
