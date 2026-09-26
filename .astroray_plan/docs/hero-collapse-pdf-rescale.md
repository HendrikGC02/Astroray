# Hero-wavelength collapse: pdf rescale (terminateSecondary)

Source: pbrt-v4 `SampledWavelengths::TerminateSecondary`, `src/pbrt/util/spectrum.h`
(Apache-2.0). On a wavelength-dependent event (dispersive refraction) only the hero
lane can follow the sampled direction, so secondary pdfs go to 0 and
`pdf[0] /= NSpectrumSamples`, guarded by `SecondaryTerminated()` so it applies once.

Why: `toXYZ` sums value*CMF/pdf over lanes with pdf != 0, then divides by N. With
one surviving lane, the /N must be cancelled by the hero pdf rescale; without it the
collapsed estimate is 1/N of the truth. Astroray omitted the rescale, so dispersive
glass transmission rendered 4x too dark on CPU and GPU (issue: search
`terminateSecondary`).

Implementation: `src/spectrum.cpp` (CPU) and `include/astroray/gpu_types.h` (GPU twin).
Consumers audited 2026-09-25: toXYZ / spectrumToXYZ, stageRegen and light-pass
accumulation, RR luminance, clamps, restir target, heroAverage (volumes), redshift
(linear in pdf), pkg189 SoA write-back (idempotent via the guard), pkg258 env-shadow
parking (pre-sample lambdas, same semantics as CPU). None double-compensates.

Gates: `tests/test_spectrum.py` (semantics + unbiased collapsed estimator),
`tests/test_dispersion_hero_collapse_energy.py` (BK7 vs matched flat IOR, 2 %).
