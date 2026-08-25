# pkg221 — photon-wavelength importance sampling from the light SPD (research note)

**CLAUDE.md §6 citation record.** This documents the algorithm behind pkg221 and
the published sources it follows; no algorithm is invented here.

## Problem

The photon-caustic pre-pass (CPU `spectral_path_tracer::buildPhotonMap`, GPU
`kEmitSceneCaustic`) drew each forward photon's wavelength **uniformly** over
[380, 720] nm and deposited pure CIE-CMF flux, never weighted by the emitting
light's spectral power distribution S(λ). For a narrow-line lamp (sodium D at
~589 nm, mercury lines) this spreads photons across the whole band → a physically
impossible **continuous rainbow** caustic, and starves the true emission-line
wavelengths of samples.

## Algorithm — spectral importance sampling (inverse-CDF of a tabulated density)

Sample λ with pdf `p(λ) = S(λ) / I`, where `I = ∫ S(λ) dλ` (discrete: `I = Σ_k
S_k · Δλ`, Δλ = 1 nm over K = 341 samples). The Monte-Carlo deposit weight is the
value over the pdf:

    power(λ) = CMF(λ) · [ S(λ) / p(λ) ] · tr · cosθ  =  CMF(λ) · I · tr · cosθ

So **when λ is sampled ∝ S, the S/p factor collapses to the constant I** — every
surviving photon carries the same spectral weight I, but the λ values now cluster
where S is large. The total deposited XYZ equals `∫ CMF(λ)·S(λ) dλ` in
expectation (the true emitted colour), with far lower variance than the naive
"uniform λ, multiply power by S(λ)" alternative (which wastes ~all photons on dead
wavelengths for a narrow line). A broadband/flat S(λ) gives I ≈ const and p ≈
uniform, so the result is unchanged up to the constant I (absorbed by the caustic
`scale = boost/(π·peak95)` calibration).

Sampling is by **inverse CDF**: build the normalized cumulative `C_k = Σ_{j≤k}
S_j / Σ_j S_j`; for u∈[0,1) binary-search the smallest k with `C_k ≥ u`, then
linearly interpolate within the [k-1,k] bin. CPU (`include/astroray/photon_spd.h`
`photonSpdInverseCdf`) and GPU (`src/gpu/photon_caustic.cu` `pc_spdInverseCdf`) use
byte-identical logic so both backends produce matching caustic spectra.

## Sources

- **PBRT-v4, §4.5.4 "Sampling the Spectral Distribution" / `SampledWavelengths`**
  (Pharr, Jakob, Humphreys — *Physically Based Rendering*, 4th ed.). The canonical
  treatment of importance-sampling wavelengths from a spectral density and the
  unbiased S/p weight. https://pbr-book.org/4ed/
- **Cycles hero-wavelength sampling** (Wilkie et al. 2014, "Hero Wavelength
  Spectral Sampling"), the convention Astroray's `SampledWavelengths` already
  follows (see pkg206). pkg221 reuses the same spectral machinery for the photon
  λ draw.
- Inverse-CDF sampling of a tabulated 1-D density is textbook (PBRT-v4 §2.4
  "Sampling Using the Inversion Method"; Devroye 1986, *Non-Uniform Random Variate
  Generation*, ch. 2).

## SPD extraction (implementation note)

The dominant light's relative SPD is read host-side via the existing
`LightSampler::sample()` API: light **selection** depends only on the RNG (a
power/tree CDF over spectrally-integrated power), so calling `sample()` with a
fresh `std::mt19937(12345)` each time selects the SAME light, and
`LightSample::emission_spec[j]` returns that light's emission at probe lane λ_j
(four grid points per call via `SampledWavelengths::fromLambdas`). No new light
accessor is added. A light with no usable SPD (Σ S = 0, e.g. an envmap-only
scene) sets `spdValid = false` → both backends keep the exact uniform-λ path, so
no scene regresses. Relates to memory `gpu-emission-is-rgb-approximated` (the SPD
is evaluated HOST-side and the CDF shipped to the device, sidestepping the GPU's
RGB-only emission limitation).
