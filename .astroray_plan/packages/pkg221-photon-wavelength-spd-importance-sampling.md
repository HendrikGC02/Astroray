# pkg221 — Photon wavelengths must be importance-sampled from the light SPD (emission-line dispersion)

**Pillar:** 3 (light transport / spectral rendering)
**Track:** A
**Status:** DONE — merged via PR #645 (`e3e1451`, importance-sample photon wavelengths from the light SPD; emission-line caustics); round closed out `4c95741`. (Header flipped 2026-08-30 during queue reconciliation — the code landed 2026-08-25 but this Status line was never updated.)
**Depends on:** TBD
**Priority:** HIGH — a physics-correctness bug: a narrow-line lamp (sodium D,
mercury lines) currently throws a full continuous rainbow caustic, which is
physically impossible. Emission-line dispersion cannot work in this path.
**Estimated effort:** M–L (host-side SPD extraction + CDF build, plumbed into two photon loops CPU+GPU; the numerics must be exactly mirrored).
**Implementer tier:** deepseek-v4-pro / sonnet, with a `cite-algorithm` step and a
`cycles-parity-reviewer` pass on the sampling math. The SPD-extraction plumbing is
the crux — read §2 carefully.
**Sequencing:** independent of pkg220, but they touch the same two kernels/loops —
land pkg220 first (the trivial seed change) then rebase this on top, OR coordinate
so both edits to `kEmitSceneCaustic` merge cleanly. Correct atomic-line lamp SPDs
(pkg222 / pkg218 Thread A) make this VISIBLY correct; without pkg222 the line
positions may be chromatically off, but this package is still correct given
whatever SPD the light carries.

---

## Root cause (CONFIRMED IN CODE this session — do not re-investigate)

Photon wavelengths are sampled **uniformly across the whole visible band** and the
deposited power is **pure CMF**, never weighted by the emitting light's spectral
power distribution. This is SPD-blind and engine-wide (BOTH backends):

- GPU: `src/gpu/photon_caustic.cu`, `kEmitSceneCaustic` ~line 166–167:
  ```
  float uLam  = pc_jitter(cell, 101u);
  float lambda = lambdaMin + (lambdaMax - lambdaMin) * uLam;   // uniform 380..720
  ```
  and the deposit ~line 216–222 is `power = CMF(λ) · tr · cosθ` — independent of any
  light SPD.
- CPU: `plugins/integrators/spectral_path_tracer.cpp`, both photon branches:
  ~line 439 (flat-prism) and ~line 479 (general BVH loop):
  ```
  const float lambda = lmin + (lmax - lmin) * u01(gen);   // uniform
  ```
  with deposit `power = cieCmf1964_10deg(λ) · tr · cosθ` (~line 468–472 / 525–529).

Consequence: for a light whose real SPD is two narrow sodium lines at ~589 nm, the
photon λ are spread uniformly 380–720 nm and each carries full CMF weight, so the
caustic is a broadband rainbow. The emission spectrum of the source is completely
ignored.

---

## Goal

Draw each photon's wavelength **∝ the emitting light's SPD** (importance sampling),
and weight the deposit so the estimator stays unbiased. Then:
- A continuous/broadband source (blackbody, D65) still produces a white caustic
  (the SPD is ~flat over the band → distribution ≈ uniform → unchanged result).
- A narrow-line lamp concentrates its photons at the emission-line wavelengths →
  the dispersed caustic shows only those spectral colors (correct emission-line
  dispersion), with far lower variance than uniform-λ + SPD-weight would give.

## The estimator (cite + get this exactly right)

`cite-algorithm` first: this is standard spectral importance sampling — cite
**PBRT-v4 §4.5.4 (SampledWavelengths / spectral MIS)** and Cycles' hero-wavelength
sampling; save a short research note to `.astroray_plan/docs/`. The math:

Let `S(λ)` be the light's relative SPD on the band `[λmin, λmax]`. Sample λ with pdf
`p(λ) = S(λ) / I`, where `I = ∫ S(λ) dλ` (discrete: `I = Σ S(λ_k)·Δλ`). Deposit
weight becomes
```
power(λ) = CMF(λ) · [ S(λ) / p(λ) ] · tr · cosθ
         = CMF(λ) · I · tr · cosθ
```
i.e. **when you importance-sample proportional to S, the S/p factor collapses to
the constant `I`** — every photon carries the same spectral weight `I`, but the λ
values now cluster where S is large. This is the whole point: no wasted photons on
dead wavelengths, and the total deposited XYZ equals `∫ CMF(λ)·S(λ) dλ` in
expectation (the true emitted color). Keep the existing `tr` (Fresnel
transmittance) and `cosθ` (Lambert) factors untouched.

Do NOT implement the naive alternative (uniform λ + multiply power by `S(λ)`): it
is unbiased but for a narrow line almost every photon carries ~0 power → the map is
starved and the caustic is pure noise. Importance sampling is required for quality,
not just correctness.

## Specification

### 1. Extract the light SPD on the host, build a CDF

Do this ONCE per render, host-side, in both `buildCausticAim`
(`gpu_wavefront_snapshot.cu` ~1262, GPU) and `buildPhotonMap`
(`spectral_path_tracer.cpp` ~339, CPU), right where the emitting light is already
probed (`lights.sample(ls, casterC, …)` — GPU ~1294, CPU ~414).

The light stores its emission as an `EmissionSpectrum`
(`include/astroray/emission_spectrum.h`), evaluable at arbitrary wavelengths via
`EmissionSpectrum::eval(const SampledWavelengths&)`. The photon aim already samples
ONE dominant light toward the caster centroid; extract THAT light's relative SPD:

- Choose a fixed grid over `[380, 720]` nm. Use **`K = 341` samples at 1 nm** (matches
  the CMF grid resolution the deposit uses) OR reuse the light's own SPD grid if it
  exposes one — 1 nm is simplest and cheap (once per render).
- For each grid λ_k, evaluate the light's relative spectral power `S_k ≥ 0`. Get it
  from the sampled light's emission spectrum. **The cleanest access that does not
  depend on which `EmissionSpectrum` variant the light holds:** evaluate the light's
  emission at a single-wavelength `SampledWavelengths` centered on λ_k and read the
  returned spectral value (the `Light::LiSample::emission_spec` from `sampleLi`, or
  the `EmissionSpectrum::eval` directly if you can reach the light's spectrum
  object). Investigate `include/astroray/light.h` (`sampleLi` returns
  `emission_spec`; ~line 119) and the concrete lights in `src/lights/` to find the
  accessor; if no clean accessor exists, add a `const EmissionSpectrum&
  emissionSpectrum() const` getter to the `Light` base + concrete lights (small,
  local, mirror it CPU-side only — the GPU reads the host-built array, see §3).
- Normalize is NOT required for sampling correctness (the CDF handles it), but
  compute `I = Σ S_k · Δλ` for the weight.
- Build the normalized CDF `C_k = (Σ_{j≤k} S_j) / Σ_j S_j`, a `K`-length array.
- **Degenerate guard:** if `I == 0` or the light has no usable SPD (or the probe
  found no light), fall back to the CURRENT uniform behavior (uniform λ, `power =
  CMF·tr·cosθ`) so no scene regresses. Signal this with a `bool spdValid` on the aim.

### 2. Inverse-CDF sample in the photon loop (CPU)

In both CPU photon branches, replace `lambda = lmin + (lmax-lmin)*u01` with an
inverse-CDF lookup: draw `u = u01(gen)`, binary-search `C_k ≥ u`, linearly
interpolate within the bin to get λ. Deposit `power = cieCmf1964_10deg(λ) · I ·
tr · cosθ` (the extra `· I` vs today; when the SPD is flat, `I` is just a global
brightness constant folded into the existing `causticScale` calibration, so
broadband scenes are unchanged up to that constant — verify the white-caustic gate).

### 3. Inverse-CDF sample in the emit kernel (GPU)

- Add to `PhotonCausticAim` (`gpu_photon_caustic.h`): `bool spdValid; float
  spdIntegral;` and a way to pass the CDF. Simplest: a fixed-size
  `float spdCdf[341];` embedded in the aim struct (1.3 KB by value is fine for a
  once-per-build POD), OR upload the CDF to `__constant__` memory in
  `cuda_photon_caustic_build` before the launch (like `uploadCausticCmf`). Prefer
  `__constant__` (the kernel reads it uniformly across a warp). Populate it from the
  host-built array in §1.
- In `kEmitSceneCaustic`: if `spdValid`, draw `u = pc_jitter(cell, 101u ^ seed)`
  (coordinate with pkg220's seed), inverse-CDF sample λ from the constant CDF
  (binary or linear scan over 341 entries — the pre-pass is not the hot kernel),
  interpolate within the bin. Deposit `power = pc_cieCmf(λ) · spdIntegral · tr ·
  cosθ`. If `!spdValid`, keep the exact current uniform path.

### 4. CPU/GPU parity of the sampling

The CDF and the inverse-CDF interpolation MUST be computed identically on both
sides (same grid, same normalization, same bin interpolation) so the two backends
produce statistically matching caustic spectra. Factor the CDF-build into one
host function used by both `buildCausticAim` and `buildPhotonMap` if practical.

## Acceptance criteria

- [ ] **White source unchanged:** a broadband/blackbody-lit glass caustic renders
      within a per-channel mean-ratio band [0.95, 1.05] of the `main` render (flat
      SPD ⇒ importance sampling ≈ uniform; the `· I` constant is absorbed by the
      caustic scale calibration). Prove the estimator didn't shift white.
- [ ] **Emission-line dispersion (headline gate):** a Sellmeier prism + a
      NARROW-LINE lamp (sodium-vapor or a synthetic single-line SPD registered via
      `register_spectral_profile`) casts a caustic whose spectral content is
      concentrated at the line color(s), NOT a full rainbow. Concretely: sample the
      caustic-region hue distribution; assert the spread of significant hues is a
      small fraction of the full-band spread a uniform-λ render produces (state the
      threshold, e.g. line-render hue-spread ≤ 0.3× uniform-render hue-spread), and
      that the dominant hue matches the lamp's line wavelength. Guard against
      salt-and-pepper false positives — visually inspect (memory
      `general-photon-loop-needs-solid-glass`).
- [ ] **Variance win:** the narrow-line caustic at fixed photon count is
      substantially LESS noisy than the naive uniform-λ+SPD-weight approach would be
      (document the deposited-photon survival fraction: importance-sampled ≫ naive).
- [ ] **Fallback safety:** a light with no SPD (or the degenerate `I==0` case)
      renders byte-identically to `main` (uniform fallback path).
- [ ] **CPU/GPU parity:** the two backends match on the narrow-line caustic within a
      per-channel mean-ratio band (independent MC streams — use mean-ratio, NOT
      SSIM; memory `ssim-wrong-gate-for-independent-rng`).
- [ ] **Register gate:** `cuobjdump -res-usage` — `kEmitSceneCaustic` REG/STACK
      tier vs `main` (the added CDF scan + constant reads should not spill; if it
      does, keep the CDF small / iterate in constant memory). Shade fleet unchanged.
- [ ] **CI green** + **HW PASS** on RTX 5070 Ti (rebuild `.pyd`, verify canonical
      `astroray.__file__` + sm_120).

## Build / verification notes

- `cite-algorithm` BEFORE coding (CLAUDE.md §6): PBRT-v4 spectral IS, Cycles hero
  wavelength. Save the note.
- Signature sweep: `buildCausticAim` and `buildPhotonMap` internals change,
  `PhotonCausticAim` grows fields, `kEmitSceneCaustic` gains args, possibly a new
  `Light::emissionSpectrum()` getter (grep every concrete light + any test mock).
- Rebuild in a worktree (PowerShell `build_cuda_worktree.bat`); serialize CUDA
  builds (memory `concurrent-nvcc-builds-kill-each-other`).
- `cycles-parity-reviewer` on the sampling math before merge.

## Reference

- `src/gpu/photon_caustic.cu` (`kEmitSceneCaustic` λ draw + deposit).
- `plugins/integrators/spectral_path_tracer.cpp` (`buildPhotonMap`, both photon
  branches ~439 / ~479, deposits ~468 / ~525).
- `include/astroray/emission_spectrum.h` (`EmissionSpectrum::eval`).
- `include/astroray/light.h` (`sampleLi` → `LiSample::emission_spec`),
  `src/lights/*.cpp`.
- `include/astroray/spectral_profile.h` (`register_spectral_profile`, SPD grid),
  `include/astroray/gpu_photon_caustic.h` (aim POD).
- Memory: `gpu-emission-is-rgb-approximated` (GPU emission is RGB-approximated —
  the photon pre-pass evaluates the SPD HOST-side and ships the CDF, sidestepping
  that limitation), `spectral-profile-edit-footguns`,
  `general-photon-loop-needs-solid-glass`, `ssim-wrong-gate-for-independent-rng`.
- pkg38/pkg195 (spectral profiles), pkg206 (hero-wavelength IS), pkg222/pkg218
  Thread A (correct atomic-line SPDs — makes this visibly right).
