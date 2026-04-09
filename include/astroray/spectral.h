#pragma once
#include "gr_types.h"
#include "../raytracer.h"   // for Vec3
#include <random>
#include <cmath>
#include <algorithm>

// ============================================================================
// Spectral rendering pipeline: Planck, hero wavelength sampling, CIE XYZ→sRGB
// Port of the validated Python spectral pipeline.
// ============================================================================

// Planck blackbody spectral radiance B(λ, T) in W/(m²·sr·m)
// wavelength_nm in nm, temperature_K in Kelvin
__attribute__((noinline)) double planck(double wavelength_nm, double temperature_K) {
    if (temperature_K <= 0.0) return 0.0;
    double lam = wavelength_nm * 1e-9;  // nm → m
    // B = (2hc²/λ⁵) / (exp(hc/(λkT)) - 1)
    double hc_lkT = (h_PLANCK * c_LIGHT) / (lam * k_BOLTZ * temperature_K);
    if (hc_lkT > 700.0) return 0.0;  // prevent exp overflow
    double expTerm = std::exp(hc_lkT) - 1.0;
    if (expTerm <= 0.0) return 0.0;
    double lam5 = lam * lam * lam * lam * lam;
    return (2.0 * h_PLANCK * c_LIGHT * c_LIGHT) / (lam5 * expTerm);
}

// Hero wavelength sample: 4 stratified wavelengths per ray
struct SpectralSample {
    double wavelengths[4];  // nm
    double radiance[4];     // accumulated spectral radiance
};

inline SpectralSample sampleHeroWavelengths(std::mt19937& gen,
                                             double lam_min = 200.0,
                                             double lam_max = 2000.0)
{
    std::uniform_real_distribution<double> dist(0.0, 1.0);
    double span  = lam_max - lam_min;
    double step  = span / 4.0;
    double hero  = lam_min + dist(gen) * step;  // hero in first stratum

    SpectralSample s;
    for (int i = 0; i < 4; ++i) {
        double lam = hero + i * step;
        // Wrap around the range
        if (lam > lam_max) lam -= span;
        s.wavelengths[i] = lam;
        s.radiance[i]    = 0.0;
    }
    return s;
}

// ============================================================================
// CIE 1931 2° color matching functions (81 entries, 380–780 nm, 5 nm spacing)
// ============================================================================
namespace cie_cmf {

static constexpr int    N     = 81;
static constexpr double START = 380.0;
static constexpr double STEP  =   5.0;

// x-bar
static constexpr double x_bar[N] = {
    0.001368, 0.002236, 0.004243, 0.007650, 0.014310, 0.023190, 0.043510,
    0.077630, 0.134380, 0.214770, 0.283900, 0.328500, 0.348280, 0.348060,
    0.336200, 0.318700, 0.290800, 0.251100, 0.195360, 0.142100, 0.095640,
    0.057950, 0.032010, 0.014700, 0.004900, 0.002400, 0.009300, 0.029100,
    0.063270, 0.109600, 0.165500, 0.225750, 0.290400, 0.359700, 0.433450,
    0.512050, 0.594500, 0.678400, 0.762100, 0.842500, 0.916300, 0.978600,
    1.026300, 1.056700, 1.062200, 1.045600, 1.002600, 0.938400, 0.854450,
    0.751400, 0.642400, 0.541900, 0.447900, 0.360800, 0.283500, 0.218700,
    0.164900, 0.121200, 0.087400, 0.063600, 0.046770, 0.032900, 0.022700,
    0.015840, 0.011359, 0.008111, 0.005790, 0.004109, 0.002899, 0.002049,
    0.001440, 0.001000, 0.000690, 0.000476, 0.000332, 0.000235, 0.000166,
    0.000117, 0.000083, 0.000059, 0.000042
};

// y-bar
static constexpr double y_bar[N] = {
    0.000039, 0.000064, 0.000120, 0.000217, 0.000396, 0.000640, 0.001210,
    0.002180, 0.004000, 0.007300, 0.011600, 0.016840, 0.023000, 0.029800,
    0.038000, 0.048000, 0.060000, 0.073900, 0.090980, 0.112600, 0.139020,
    0.169300, 0.208020, 0.258600, 0.323000, 0.407300, 0.503000, 0.608200,
    0.710000, 0.793200, 0.862000, 0.914850, 0.954000, 0.980300, 0.994950,
    1.000000, 0.995000, 0.978600, 0.952000, 0.915400, 0.870000, 0.816300,
    0.757000, 0.694900, 0.631000, 0.566800, 0.503000, 0.441200, 0.381000,
    0.321000, 0.265000, 0.217000, 0.175000, 0.138200, 0.107000, 0.081600,
    0.061000, 0.044580, 0.032000, 0.023200, 0.017000, 0.011920, 0.008210,
    0.005723, 0.004102, 0.002929, 0.002091, 0.001484, 0.001047, 0.000740,
    0.000520, 0.000361, 0.000249, 0.000172, 0.000120, 0.000085, 0.000060,
    0.000042, 0.000030, 0.000021, 0.000015
};

// z-bar
static constexpr double z_bar[N] = {
    0.006450, 0.010550, 0.020050, 0.036210, 0.067850, 0.110200, 0.207400,
    0.371300, 0.645600, 1.039050, 1.385600, 1.622960, 1.747060, 1.782600,
    1.772110, 1.744100, 1.669200, 1.528100, 1.287640, 1.041900, 0.812950,
    0.616200, 0.465180, 0.353300, 0.272000, 0.212300, 0.158200, 0.111700,
    0.078250, 0.057250, 0.042160, 0.029840, 0.020300, 0.013400, 0.008750,
    0.005750, 0.003900, 0.002750, 0.002100, 0.001800, 0.001650, 0.001400,
    0.001100, 0.001000, 0.000800, 0.000600, 0.000340, 0.000240, 0.000190,
    0.000100, 0.000050, 0.000030, 0.000020, 0.000010, 0.000000, 0.000000,
    0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
    0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
    0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
    0.000000, 0.000000, 0.000000, 0.000000
};

// Evaluate a CMF at arbitrary wavelength (nm) by linear interpolation
inline double eval(const double* cmf, double lam) {
    double idx = (lam - START) / STEP;
    if (idx < 0.0 || idx >= double(N - 1)) return 0.0;
    int i0 = int(idx);
    double frac = idx - i0;
    return cmf[i0] * (1.0 - frac) + cmf[i0 + 1] * frac;
}

} // namespace cie_cmf

// Convert accumulated SpectralSample to CIE XYZ (Vec3, float)
__attribute__((noinline)) Vec3 spectralToXYZ(const SpectralSample& s) {
    double X = 0, Y = 0, Z = 0;
    for (int i = 0; i < 4; ++i) {
        double lam = s.wavelengths[i];
        double L   = s.radiance[i];
        X += L * cie_cmf::eval(cie_cmf::x_bar, lam);
        Y += L * cie_cmf::eval(cie_cmf::y_bar, lam);
        Z += L * cie_cmf::eval(cie_cmf::z_bar, lam);
    }
    // Average over the 4 wavelengths
    X /= 4.0;  Y /= 4.0;  Z /= 4.0;
    return Vec3(float(X), float(Y), float(Z));
}

// CIE XYZ → linear sRGB (D65 white point)
inline Vec3 xyzToLinearSRGB(const Vec3& xyz) {
    float r =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
    float g = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
    float b =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;

    // Desaturate out-of-gamut colours toward white
    float minC = std::min({r, g, b});
    if (minC < 0.0f) {
        r -= minC;  g -= minC;  b -= minC;
    }
    return Vec3(r, g, b);
}

// Full pipeline: SpectralSample → linear sRGB, with optional exposure scaling
// exposure == 0 means no scaling (caller handles auto-exposure externally)
__attribute__((noinline)) Vec3 spectralToRGB(const SpectralSample& s, float exposureScale = 1.0f) {
    Vec3 xyz = spectralToXYZ(s);
    xyz = xyz * exposureScale;
    return xyzToLinearSRGB(xyz);
}
