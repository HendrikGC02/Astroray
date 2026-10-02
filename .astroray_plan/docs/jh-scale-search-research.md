# JH scale-grid search (#1012)

- Jakob & Hanika 2019, "A Low-Dimensional Function Space for Efficient Spectral Upsampling", EG 2019, DOI 10.1111/cgf.13626.
- Reference: mitsuba-renderer/rgb2spec (BSD-3-Clause). `rgb2spec_opt.cpp` generates the z axis as
  `scale[k] = smoothstep(smoothstep(k/(res-1)))` (monotone, non-uniform), so a direct index needs the inverse of a
  double smoothstep with float rounding; bisection is exact by construction and 6 steps for res=64.
- pbrt-v4 `FindInterval` (BSD-2) is the same bisection used to locate the interval.
- Chosen: bisection `astroray::jhFindScaleIndex` (include/astroray/spectrum.h), shared by CPU `JakobHanikaLut::lookup`
  and device `gpu_jhLookupCoeffs`; returns the same k as the former linear scan for any monotone table.
- Coefficients are looked up once per RGB (`gpu_rgbToSampledSpectrum`) and the sigmoid evaluated per wavelength.
