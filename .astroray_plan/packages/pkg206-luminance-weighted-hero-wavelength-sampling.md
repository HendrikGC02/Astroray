# pkg206 — Luminance-weighted hero-wavelength importance sampling (D65 CDF + constant fit)

**Pillar:** 3 (light transport / spectral rendering) + Integration Milestone (Cycles-parity)
**Track:** A
**Status:** open (filed 2026-08-19).
**Estimated effort:** M (CPU+GPU byte-mirrored sampler change + pdf plumbing + re-baseline).
**Depends on:** nothing hard. Composes with pkg189 (GPU hero-λ dispersion, LANDED) and
the existing spectral MIS caustic path (SMS). CPU/GPU byte-mirrored in the SAME PR.

## Goal

Astroray draws the hero wavelength **uniformly** over the full range
(`SampledWavelengths::sampleUniform`, `src/spectrum.cpp:82-100`, and its GPU mirror
`sampleUniformWavelength`, `src/gpu/wavefront/stage_init.cu:113-128`): hero =
`lambdaMin + u*span`, three stratified companions wrapped into range, every
`pdf = 1/span`. Uniform draws put equal sampling effort on wavelengths the eye
barely sees, so dispersive-caustic renders carry more chromatic noise per sample
than necessary — the exact regime where the `hue_spread`/`bright_coverage` gates
already fight noise (2026-08-19 dispersion research report §6.3).

Cycles' merged dispersion PR (#162041) draws the hero wavelength from a
**luminance-weighted D65 distribution**, fitted to a sigmoid CDF, with a constant
added to the CIE luminance CMF before fitting ("we want a bit of all the
wavelengths") so it lands between pure-luminance (smooth body, green caustic noise)
and uniform (noisier everywhere). This is the one concrete convergence win the
Cycles author measured. **Adopt a luminance-weighted hero-wavelength importance
sampling proposal for Astroray's spectral sampler**, CPU+GPU byte-mirrored, with
the per-sample pdf updated to the non-uniform density so the estimator stays
unbiased.

## Specification

1. **Invoke `cite-algorithm` BEFORE writing code** (CLAUDE.md §6). Cite:
   - **Wilkie, Nawaz, Droske, Weidlich, Hanika 2014, "Hero Wavelength Spectral
     Sampling", CGF 33(4), DOI 10.1111/cgf.12419** — the canonical hero-wavelength
     framework and the multi-wavelength pdf/MIS treatment that governs how the
     companion pdfs must be set under a non-uniform hero draw.
   - **Cycles merged commit `f15daf81bf7c…`**, `intern/cycles/kernel/util/colorspace.h`
     `sample_wavelength()` (the sigmoid-CDF inverse: `rand = N*rand + y0;
     prob = a*rand*(1-rand); wavelength = -logf(1/rand - 1)/a + x0`) and the
     `cie_d65_luminance_fit.py` fit script (the a/x0/y0/N constants + the "add a
     constant to the luminance CMF" trick), quoted under Apache-2.0 for research.
   - Astroray already carries the **CIE 1964 10° observer** and a D65 SPD; derive
     the luminance-weight target from those (do NOT hardcode Cycles' CIE-1931-2°
     fit constants blindly — Astroray's observer differs; either re-fit against
     Astroray's own D65×CMF luminance or justify reusing Cycles' constants with a
     measured error bound). Save a research note under `.astroray_plan/docs/`
     (fit derivation + constants + the observer-mismatch decision) and cite it
     inline in both the CPU and GPU code.

2. **Replace the uniform hero draw** in `SampledWavelengths::sampleUniform` (add a
   new `sampleImportance`/`sampleLuminanceWeighted` method rather than silently
   changing `sampleUniform`'s contract — other callers, e.g. `emission_spectrum.cpp`,
   `area_light.cpp`, `distant_light.cpp`, `redshift`, rely on the uniform form).
   The new sampler: draw hero λ from the inverse sigmoid CDF; set the **hero pdf**
   to the sigmoid-derivative density (`prob` above, in 1/wavelength units); keep
   the stratified companion offsets but set **each companion pdf to the density
   evaluated at its own λ** (per Wilkie 2014 — NOT `1/span`). Route the primary
   path init (`src/cpu/wavefront/path_kernel.cpp:94`,
   `reference_pt_production.cpp:312`, and the GPU `stage_init.cu:211` call site) to
   the new sampler; leave light/emission/redshift callers on `sampleUniform`.

3. **CRITICAL — byte-mirror CPU and GPU in the SAME PR** (memory: CPU/GPU spectral
   work is byte-mirrored, never split). The GPU `sampleUniformWavelength` twin gets
   an identical `sampleImportanceWavelength` with the same constants and the same
   pdf formula. Add a cross-reference comment on each side. Watch the RNG draw
   COUNT: the new sampler must consume the SAME number of uniforms as the old
   (one `u`) so the CPU↔GPU dimension counters stay aligned (memory:
   `stage_init.cu:98-112` documents the 8.7M-ULP divergence a draw-count mismatch
   caused).

4. **Register discipline (GPU).** The new sampler adds a `logf`/sigmoid eval at
   path init (`stage_init`/`generatePrimaryRay`, REG 127 tier — clear headroom),
   NOT in the register-pinned `stageShadeBucketedKernel` (254). Confirm the shade
   kernel fleet baseline is byte-identical (`<0,0,0,0,0>` REG 254 / STACK 3352 /
   CONSTANT[0] 1700) after the change — the sampler must not leak into the shade
   path. `cuobjdump --list-elf` (sm_120 first) + `-res-usage` on the final linked
   `.pyd`, mtime stated.

5. **Re-baseline** any test that pins `pdf == 1/span` or the uniform hero
   distribution on the PRIMARY path. Grep for `sampleUniform` assertions and the
   spectral-prism / caustic convergence gates; update expected pdfs, keep unbiasedness
   gates (furnace / white-balance) passing unchanged.

## Acceptance

- [ ] `cite-algorithm` invoked; research note (fit derivation + observer-mismatch
  decision) lands in `.astroray_plan/docs/`; CPU + GPU code cite Wilkie 2014 +
  the Cycles fit inline.
- [ ] **Convergence win measured, not assumed:** at a FIXED low sample count, the
  dispersive-prism / spectral-caustic scene (`tests/test_spectral_prism.py`,
  the SMS caustic path) shows **lower chromatic noise** under importance sampling
  than under uniform — report a variance/MSE-vs-reference or a per-channel noise
  metric A/B (uniform vs importance), LINEAR EXRs, seed-pinned. State the `.pyd`
  mtime next to the render leg.
- [ ] **Unbiasedness preserved:** a white/neutral furnace and a converged
  (high-spp) prism render match the uniform-sampler result to within MC noise
  (per-channel mean-ratio band, memory `ssim-wrong-gate-for-independent-rng` /
  `gamma-furnace-cannot-detect-energy-gain` — render LINEAR with an upper bound).
- [ ] CPU↔GPU parity: same-scene same-seed CPU-vs-GPU comparison agrees
  (per-channel mean-ratio band); the sampler constants + pdf formula are
  byte-identical between the two code sites (show both snippets in the PR).
- [ ] Shade-kernel fleet register HARD gate unchanged (254/3352/1700); RNG
  draw-count unchanged (CPU↔GPU dimension counters aligned).
- [ ] Re-baselined tests pass; furnace/anti-alias/convergence gates pass; CI green
  on all matrix jobs (`gh run view` HEAD) AND the RTX leg (memory
  `ci_has_no_gpu_runtime_blindspot`).

## Non-goals

- **No per-bounce λ re-sampling / spectral MIS** (that is pkg211 — this package
  keeps the ONE-hero-per-path structure; only the hero *proposal density* changes).
- **No change to the λ→RGB path** (Astroray carries the spectrum to the CIE-1964
  observer; no D65 uplift is needed — that is Cycles' RGB-renderer workaround).
- **No new artist knob** — this is an internal sampler quality change, invisible
  in the UI.

## Provenance

Filed by the architect 2026-08-19 from the dispersion research report
(`.astroray_plan/docs/reports/2026-08-19-cycles-dispersion-research.html` §6.3,
ranked recommendation #3 — the OWNER'S priority). Grounded in live code:
`src/spectrum.cpp:82-100` (CPU uniform hero), `src/gpu/wavefront/stage_init.cu:113-128`
(GPU mirror), primary call sites `path_kernel.cpp:94` / `stage_init.cu:211`.
Open-model IMPLEMENT-tier candidate behind build + CI + RTX gates; Claude owns the
observer-mismatch fit decision, the unbiasedness verification, and the register/
draw-count check.
