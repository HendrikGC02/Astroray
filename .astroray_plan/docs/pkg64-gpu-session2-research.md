# pkg64-gpu Session 2 — Research notes (2026-05-28)

**Author:** Claude Code overnight session
**Status:** investigation only, no implementation landed
**Triggers acceptance:** Phase 1 of pkg64-gpu-sellmeier-session2-multi-ior

---

## Goal recap

Close the deferred Phase 3 gates from pkg64-gpu Session 1 (PR #354):
- `test_pkg64_gpu_cpu_parity_ssim`: SSIM ≥ 0.97 (baseline 0.523)
- `test_pkg64_gpu_phase3_prism_psnr_floor`: PSNR floor ≥ −0.5 dB (baseline −2.13 dB)

Without losing the receiver-energy gate (≥ 1.10×, baseline 1.17×).

---

## What I tried tonight

**Naive "mirror CPU" approach:** call `lambdas.terminateSecondary()` on the GPU dielectric path after a wavelength-dependent refraction (mirrors `plugins/materials/dielectric.cpp:181-188` exactly).

**Result:** the receiver-energy gate regressed from 1.17× → 0.98× (caustic energy effectively vanishes). SSIM did NOT improve — it went from 0.523 → 0.485.

**Diagnosis:** terminating secondaries on the GPU side reduces the spectral throughput by ~4× (only the hero contributes after the dispersive vertex). The CPU does the same operation but its receiver-energy gate continues to pass; either:
1. The CPU's spectral path-integration applies a compensation factor that the GPU integration doesn't.
2. The CPU's deferred-tests baseline was captured with `terminateSecondary` active AND a smaller absolute energy.
3. The GPU receiver-energy gate compares with-caustics-ON vs OFF, and the OFF baseline implicitly carries the 4-wavelength contribution; after `terminateSecondary` only the ON branch shrinks, breaking the ratio.

Hypothesis (3) is the most plausible: the test reads `ratio = E_on / E_off`. Before my change, both branches were at "4-wavelength energy" so the caustic energy added a clean +17%. After my change, the ON branch's caustic contribution is per-ray ~1/4 the size, so the ratio drops below 1.0.

The fix is therefore NOT a one-line `terminateSecondary` call. It needs either:
- A compensation factor that re-normalises the hero's contribution to account for the killed secondaries (the actual Wilkie 2014 hero-wavelength MIS formulation).
- Or splitting into N rays per dispersive hit (Option A from the spec).

This matches what the original spec said: Option B is NOT a trivial port; it's a real MIS implementation. The "naive terminate-only" approach is below what Session 2 actually needs.

---

## What the proper Option B implementation looks like

Cycles `intern/cycles/kernel/svm/closure_principled.h` hero-wavelength branch (Apache-2.0). Key points:

1. **At a dispersive vertex**, evaluate `n(λ_i)` for **all** sampled wavelengths.
2. **Pick the hero** wavelength's refraction direction.
3. **Compute MIS weight** per wavelength i: `w_i = power_heuristic(pdf_i_at_hero_direction, sum_j(pdf_j))`. For delta materials, `pdf_i` at the hero's direction is 1 if `n_i == n_hero` (i.e., only the hero itself contributes), else 0. This effectively makes the weights `[1, 0, 0, 0]` — the hero gets full weight, others get zero.
4. **Update throughput**: `throughput[i] *= w_i * eta_i^2` for each i. For Option B's full formulation, `w_i` is the MIS weight (1 for hero, 0 for others at a delta vertex), so secondaries DO get killed — but the hero is NOT also scaled by 1/4. So the energy is preserved.

The key difference from the naive `terminateSecondary` approach: in proper MIS, the hero's contribution is **not divided by N**. The hero carries the full energy because we sampled it with the full pdf.

In practice: `throughput[hero] *= eta^2` (unchanged), `throughput[non-hero] *= 0`. The pdf array gets `[1, 0, 0, 0]` in some sense, but the wavelength sample-count is preserved by the path's downstream integration.

---

## Recommended Phase 2 implementation

```cuda
__device__ inline GBSDFSample gpu_dielectric_sample_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo,
    GSampledWavelengths& lambdas, curandState* rng)
{
    GBSDFSample s;
    s.isDelta = true;
    rec.isDelta = true;

    // Evaluate IOR at hero — same as Session 1.
    float ior = mat.isDispersive
        ? gpu_sellmeier_ior(mat.dispersion, lambdas.lambda[0])
        : mat.ior;

    // ... compute fresnel, decide reflect vs refract ...

    if (reflected) {
        s.wi  = ...;
        s.f   = GVec3(1.f);   // wavelength-independent at reflection
        s.pdf = 1.f;
    } else {
        s.wi  = ...refract at hero IOR...;
        // The hero gets full throughput (NOT divided by N).
        s.f   = GVec3(eta * eta);
        s.pdf = 1.f;

        // KEY: also need to set s.fSpectral here, NOT compute it from s.f.
        // The hero gets eta^2; secondaries get 0.
        if (mat.isDispersive) {
            // Override the default RGB→spectrum conversion at this vertex.
            // hero throughput = eta^2 * (hero's RGB→spectrum at λ_hero)
            // secondary throughput = 0
            // This requires gpu_material_sample_spectral to honour an
            // override flag from gpu_dielectric_sample_spectral.
            s.fSpectral[0] = (eta * eta) * gpu_rgbSpectrumAt(GVec3(1.f), lambdas.lambda[0], mat.spectralMode);
            for (int i = 1; i < G_SPECTRUM_SAMPLES; ++i) {
                s.fSpectral[i] = 0.f;
            }
            // Also flag the wavelengths so downstream NEE / RR can see this.
            lambdas.terminateSecondary();  // OK to do this here for downstream behaviour
            s.useExplicitSpectral = true;   // new field — see below
        }
    }
    return s;
}
```

This requires adding a `useExplicitSpectral` flag to `GBSDFSample` so `gpu_material_sample_spectral` doesn't overwrite the explicit per-wavelength values with RGB→spectrum conversion. Then in the calling kernel:

```cuda
if (bs.useExplicitSpectral) {
    // Don't recompute from s.f.
} else {
    bs.fSpectral = gpu_rgbToSampledSpectrum(bs.f, wl, mat.spectralMode);
}
```

---

## Why this is a tomorrow-job, not a tonight-job

The above involves:
1. Adding a field to `GBSDFSample` (every kernel that constructs one must initialise it).
2. Modifying both `multiwavelength_kernel.cu` and `path_trace_kernel.cu` callers.
3. Verifying the receiver-energy gate stays passing (the math has to balance such that hero's full eta² ≈ old per-ray's RGB-uniform eta² × 4-wavelength-sum).
4. Visual + numeric validation against CPU baseline.

Each step is a CUDA build cycle (~5 minutes). Steps 3-4 need RTX hardware testing. A clean implementation is ~½ day of focused work; rolling it out under unsupervised overnight with bisecting the energy mismatch is high-risk.

---

## Recommendation

- **Do not implement Session 2 tonight.** The naive `terminateSecondary` patch broke the receiver-energy gate, and the proper MIS implementation needs a non-trivial integration-side change that should be done with the owner's eyes on the math.
- **Keep Session 1's hero-only GPU dielectric as the shipping baseline.** Receiver-energy gate passes; PSNR/SSIM remain documented as deferred.
- **File this note as the Phase 1 artifact** so a future implementation session can pick up cold with the implementation sketch above.
- **The pkg104 reference bank's `prism-bk7-collimated` scene runs on CPU** (forced via the SMS caustic integrator, which is CPU-only). The visible chromatic ring is already there. GPU port of that scene is gated on this work landing properly.

---

## Update 2026-05-28 (morning) — Session 2 Phase 2 attempt revisited

Tried the `useExplicitSpectral` approach sketched above. Result: the math is more interlocked than the sketch suggested.

**Attempt A — explicit per-wavelength fSpectral (hero gets eta², secondaries 0):**
- Receiver-energy gate: 1.17× → 0.98× (regressed, same as the naive try).
- SSIM vs CPU: 0.523 → 0.485 (slightly worse).
- Root cause: the `spectrumToXYZ` integrator divides by `1/G_SPECTRUM_SAMPLES = 1/4` regardless of how many wavelengths are alive. Hero contributes 1× and gets divided by 4 → 1/4 of the all-4-alive integrated radiance.

**Attempt B — hero gets `N × eta² × hero_spec` (compensate the 1/N divisor):**
- Receiver-energy gate: 1.17× → **passed** (1.64× — actually too bright).
- SSIM vs CPU: 0.523 → 0.377 (worse).
- The N× compensation overshoots: per-ray hero now carries 4× the energy it should, and the MC estimator over many rays converges to 4× the integral.

**Attempt C — change `spectrumToXYZ` to divide by alive-count (not N):**
- Combined with Attempt A (hero at plain eta²): receiver energy 1.17× → 1.47× (still too bright), SSIM = 0.481.
- The CPU's `SampledSpectrum::toXYZ` ALSO uses `1/N`, not alive-count. So changing only the GPU asymmetrically breaks CPU↔GPU parity even when both terminate secondaries correctly.

**Hard conclusion:** Session 2 needs the CHANGE TO BE COORDINATED across:
1. **CPU + GPU spectrum integration** (both should consistently normalise — likely keep 1/N for unbiased MC over many rays; the per-ray reduction is the natural variance cost, not a bug).
2. **The receiver-energy and SSIM tests** (their baselines may have been captured before the spec's hero-wavelength semantics were intended; the 1.17× baseline assumed 4-wavelength-broadcast behavior which is monochromatic-by-design).
3. **Possibly the wavelength-stratification scheme** (Cycles uses RR-style hero selection that the path-length-averaging absorbs naturally; Astroray's static 4-per-ray stratification doesn't average as cleanly when individual rays kill secondaries).

This is **at least a full day of integrator-side surgery + owner-eyes-on-math + RTX baseline re-pinning**. The naive port produces wrong numbers in three different ways depending on which compensation you try. Filing this update so the next implementation session doesn't waste cycles re-walking these dead ends.

**Action for owner:** when ready to pick up Session 2, the right entry point is probably the CPU `SampledSpectrum::toXYZ` + `dielectric.cpp:181-188` pair — verify that the CPU is ALSO undergoing the 1/4 energy reduction we measured on GPU (it may be, and it may simply not be a gated test there). If yes, the per-ray reduction is the expected MC variance and the test baselines need updating. If no, there's some compensation in CPU's path-integrator that isn't on GPU and we need to find it.

**Code-side artifact:** three files were modified and reverted today (`gpu_types.h`, `gpu_materials.h`, `multiwavelength_kernel.cu`). The hero-only Session 1 behavior remains as shipped. No engine changes ship from this session.

---

## Update 2026-05-28 (afternoon, supervised session) — ROOT CAUSE FOUND

The three morning attempts chased the wrong variable (energy normalization). The
actual SSIM-killer is a **hero-wavelength distribution bug** in the GPU sampler,
and the receiver-energy collapse is explained by a **missing PBRT compensation
term** in `terminateSecondary`. Both are concrete and citable.

### Canonical paper

- **Title:** Hero Wavelength Spectral Sampling
- **Authors:** A. Wilkie, S. Nawaz, M. Droske, A. Weidlich, J. Hanika
- **Year / Venue:** 2014, EGSR (Eurographics Symposium on Rendering); Computer
  Graphics Forum 33(4):123–131.
- **DOI:** 10.1111/cgf.12419
- **PDF:** https://cgg.mff.cuni.cz/publications/hero-wavelength-spectral-sampling/
- **Core idea:** sample one *hero* wavelength λ_h uniformly per path; place the
  C−1 secondaries at equal spacing so the C samples evenly cover the band; do
  all directional sampling with the hero; combine the per-wavelength estimators
  with MIS (balance/power heuristic over the C wavelength pdfs at the sampled
  direction). At a **delta (perfectly specular) dispersive interface** each
  wavelength refracts at a *different* angle, so only the hero's pdf is nonzero
  at the sampled direction → the MIS weights collapse to `[1,0,0,…]` and the
  secondaries must be dropped. This is the `terminateSecondary` case.

### Reference implementation (license-compatible)

- **Repo:** PBRT-v4 — https://github.com/mmp/pbrt-v4
- **File:** `src/pbrt/util/spectrum.h` — `class SampledWavelengths`.
- **License:** Apache-2.0 → compatible with Astroray's MIT (permissive; we port
  the *idea/term*, with attribution, not a verbatim copy).
- The canonical `TerminateSecondary()` body (retrieved 2026-05-28):
  ```cpp
  void TerminateSecondary() {
      if (SecondaryTerminated()) return;
      for (int i = 1; i < NSpectrumSamples; ++i) pdf[i] = 0;
      pdf[0] /= NSpectrumSamples;          // <-- THE COMPENSATION TERM
  }
  ```
  PBRT's `SampledSpectrum::ToXYZ` divides by `NSpectrumSamples` via `.Average()`
  (same structure as Astroray `toXYZ`'s `1/N`). The `pdf[0] /= N` line cancels
  that `1/N` for the surviving hero, so a terminated dispersive path is an
  **unbiased** single-hero estimate. Without it the path is N× too dark.
- Spec also names Cycles `closure_principled.h` (hero branch) and PBRT-v4
  `bxdfs.h DielectricBxDF::Sample_f`; PBRT's `SampledWavelengths` is the cleaner
  citation for the *normalization* term that Astroray is missing.

### Bug 1 (load-bearing): GPU hero-wavelength distribution

`src/gpu/multiwavelength_kernel.cu::gpu_sampleBandWavelengths` (and the twin
`include/astroray/gpu_materials.h::gpu_sampleUniformWavelengths`) compute
`offset=(u+i)/N` ⇒ `λ[0] = lmin + (u/N)·span` — the hero is confined to the
**first 1/N of the band** (with the prism's [380,780] band: λ[0]∈[380,480),
pure violet/blue). CPU `SampledWavelengths::sampleUniform` (`src/spectrum.cpp:82`)
and the *already-fixed* wavefront `src/gpu/wavefront/stage_init.cu:64` use
`hero = lmin + u·span` ⇒ λ[0] spans the **full band**. Verified numerically:
CPU hero mean 580 nm (full band), GPU multiwave hero mean 430 nm (violet).
The 4-sample *sets* are statistically identical; only element [0] (the survivor
+ the SMS-caustic colorizing wavelength) differs. The fix already exists in
`stage_init.cu` — it was never propagated to the multiwavelength kernel. This
single bug confined the GPU prism caustic to violet (near-zero CMF_Y luminance),
which is why all three morning attempts failed on *both* SSIM and energy, and
why energy-normalization tweaks could never fix it.

### Bug 2: missing compensation term (shared CPU + GPU spectral core)

`astroray::SampledWavelengths::terminateSecondary()` (`src/spectrum.cpp:102`) and
`GSampledWavelengths::terminateSecondary()` (`include/astroray/gpu_types.h:102`)
both zero the secondary pdfs but **never divide `pdf[0]` by N** — they are an
incomplete port of PBRT's `TerminateSecondary`. No integrator compensates
elsewhere (`secondaryTerminated()` is exposed via the pybind binding but is not
read by any integrator). Consequence: every Astroray dispersive caustic — CPU
*and* GPU — is N× (≈4×) too dark in absolute terms. Parity holds (both equally
dark) so the GPU↔CPU SSIM gate is unaffected, but the GPU receiver-energy
ON/OFF ratio gate (fixed 1.045× threshold, luminance-weighted) is at risk: at
1/N weight the chromatic caustic adds only ~4–5% in-window luminance, right at
the gate. The SMS caustic hooks (`plugins/integrators/sms_caustic_path_tracer.cpp`
out[0]=heroAccum; `multiwavelength_kernel.cu` smsContrib.v[0]=sampleHero) bypass
`terminateSecondary` entirely, so the term has to be applied there as an explicit
`×N` on the hero-only contribution.

### What we reproduce vs deliberately omit

- **Reproduce:** Wilkie hero sampling layout (full-band hero) + the PBRT
  `pdf[0]/=N` delta-collapse normalization.
- **Omit:** the general non-delta MIS power-heuristic branch. Astroray's
  dielectric is pure specular (no roughness); no gate exercises a rough
  dispersive closure, so writing that branch would be unreachable, untested
  code (CLAUDE.md §2). Documented here as a future package if a glossy
  dispersive material is ever added.

### Implementation plan (incremental, measure before expanding scope)

**Phase 2a (GPU-only, no CPU-output change, reversible):**
1. Fix `gpu_sampleBandWavelengths` (+ `gpu_sampleUniformWavelengths`) to the CPU
   `hero = lmin + u·span` layout, matching `stage_init.cu`.
2. Mirror CPU's current `terminateSecondary` in the GPU dielectric refraction
   (`gpu_materials.h:294`), making `lambdas` non-const.
3. Build, run the 3 gates + reference-bank prism on RTX. Measure.

**Phase 2b (only if 2a leaves receiver-energy < 1.045× or SSIM short) — touches
the shared CPU spectral core, OWNER SIGN-OFF REQUIRED:**
4. Add `pdf[0] /= N` to *both* `SampledWavelengths::terminateSecondary` (CPU) and
   `GSampledWavelengths::terminateSecondary` (GPU) — the PBRT term.
5. Multiply the hero-only SMS caustic contribution by N in *both* SMS hooks.
6. Re-bless CPU baselines + the reference-bank prism (CPU caustics brighten ≈N×);
   sweep CPU dispersive tests (test_pkg64_phase3_* CPU, test_pkg31, test_pkg13,
   test_spectral_*) for shifted pins.

### Citation block for the code

```cpp
// Hero-wavelength spectral sampling: Wilkie, Nawaz, Droske, Weidlich, Hanika,
// "Hero Wavelength Spectral Sampling", EGSR 2014, CGF 33(4):123-131.
// DOI:10.1111/cgf.12419. Delta-dispersive interface collapses the MIS weights
// to hero-only (terminate secondaries). Normalization term mirrors PBRT-v4
// (Apache-2.0) src/pbrt/util/spectrum.h SampledWavelengths::TerminateSecondary
// (pdf[0] /= NSpectrumSamples). Hero-band layout mirrors CPU sampleUniform
// (src/spectrum.cpp:82) and wavefront stage_init.cu:64.
```
