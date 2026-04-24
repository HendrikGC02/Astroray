#pragma once

// Pillar 2 spectral core (pkg10 — scaffolding only).
//
// New spectral types that will drive the Pillar 2 light-transport rewrite.
// Design ports the shape of PBRT v4's `SampledSpectrum`/`SampledWavelengths`
// and the Jakob-Hanika 2019 RGB-to-spectrum upsampling path; no PBRT code
// is vendored. The existing `include/astroray/spectral.h` (CIE 1931 2°,
// 380-780 nm, double) remains the authoritative GR spectral pipeline and
// is untouched by this package.
//
// Scope (see .astroray_plan/packages/pkg10-spectral-types.md):
//   * Types only. No integrator, material, pass, or env-map consumes them.
//   * 4 hero wavelength samples over 360-830 nm, float precision.
//   * sRGB upsampling via a Jakob-Hanika LUT loaded lazily from
//     data/spectra/rgb_to_spectrum_srgb.coeff.

#include <array>
#include <cstdint>
#include <string>

namespace astroray {

inline constexpr int   kSpectrumSamples = 4;
inline constexpr float kLambdaMin       = 360.0f;
inline constexpr float kLambdaMax       = 830.0f;

struct XYZ { float X = 0.0f; float Y = 0.0f; float Z = 0.0f; };

// Return the CIE 1964 10 degree standard observer CMF value at the given
// wavelength. Outside [kLambdaMin, kLambdaMax] returns zeros.
XYZ cieCmf1964_10deg(float lambda);

// Return the normalized CIE Standard Illuminant D65 SPD at the given
// wavelength. Normalization: the SPD integrated against the 1964 10° CMF
// gives Y = 1.0 (relative colorimetry for a perfect reflector).
float sampleD65(float lambda);

// Filesystem path of the shipped Jakob-Hanika sRGB LUT. Resolved lazily on
// first call; see src/spectrum.cpp for the search order.
std::string spectrumLutPath();

// --------------------------------------------------------------------------
// SampledWavelengths — a bundle of `kSpectrumSamples` wavelengths with
// their sampling PDFs, carried along a path.
// --------------------------------------------------------------------------
class SampledWavelengths {
public:
    // Stratified-uniform sample over [lambdaMin, lambdaMax]. `u` in [0, 1).
    static SampledWavelengths sampleUniform(float u,
                                            float lambdaMin = kLambdaMin,
                                            float lambdaMax = kLambdaMax);

    float lambda(int i) const { return lambdas_[i]; }
    float pdf(int i)    const { return pdfs_[i]; }

    const std::array<float, kSpectrumSamples>& lambdas() const { return lambdas_; }
    const std::array<float, kSpectrumSamples>& pdfs()    const { return pdfs_; }

    // Collapse to the hero wavelength: zero the PDFs of the secondary
    // samples. Called when a BSDF interaction is wavelength-dependent
    // (dispersion, volumetric) and cannot sample all 4 samples coherently.
    void terminateSecondary();
    bool secondaryTerminated() const;

    bool operator==(const SampledWavelengths& o) const {
        return lambdas_ == o.lambdas_ && pdfs_ == o.pdfs_;
    }

private:
    std::array<float, kSpectrumSamples> lambdas_{};
    std::array<float, kSpectrumSamples> pdfs_{};
};

// --------------------------------------------------------------------------
// SampledSpectrum — `kSpectrumSamples` spectral values, one per wavelength
// carried in a `SampledWavelengths`.
// --------------------------------------------------------------------------
class SampledSpectrum {
public:
    SampledSpectrum() = default;
    explicit SampledSpectrum(float v) { v_.fill(v); }
    explicit SampledSpectrum(const std::array<float, kSpectrumSamples>& v) : v_(v) {}

    float operator[](int i) const { return v_[i]; }
    float& operator[](int i)      { return v_[i]; }

    SampledSpectrum operator+(const SampledSpectrum& o) const;
    SampledSpectrum operator-(const SampledSpectrum& o) const;
    SampledSpectrum operator*(const SampledSpectrum& o) const;
    SampledSpectrum operator/(const SampledSpectrum& o) const;
    SampledSpectrum operator*(float s) const;
    SampledSpectrum operator/(float s) const;
    SampledSpectrum operator-() const;

    SampledSpectrum& operator+=(const SampledSpectrum& o);
    SampledSpectrum& operator-=(const SampledSpectrum& o);
    SampledSpectrum& operator*=(const SampledSpectrum& o);
    SampledSpectrum& operator*=(float s);

    bool operator==(const SampledSpectrum& o) const { return v_ == o.v_; }

    float sum()      const;
    float average()  const;
    float maxValue() const;
    float minValue() const;
    bool  hasNaN()   const;
    bool  isZero()   const;

    // Convert to CIE XYZ tristimulus given the wavelengths these samples
    // are associated with. Integrates via Monte Carlo: for each sample,
    // contribution is value * CMF(lambda_i) / pdf(i), averaged over
    // kSpectrumSamples (PBRT convention).
    XYZ toXYZ(const SampledWavelengths& wl) const;

    const std::array<float, kSpectrumSamples>& values() const { return v_; }

private:
    std::array<float, kSpectrumSamples> v_{};
};

inline SampledSpectrum operator*(float s, const SampledSpectrum& x) { return x * s; }

// --------------------------------------------------------------------------
// RGB-to-spectrum upsampling (Jakob & Hanika 2019).
//
// Construction looks the 3D sigmoid coefficient (c0, c1, c2) up in the
// shipped sRGB LUT; `sample()` evaluates the sigmoid at a set of
// wavelengths. The three variants differ in how the magnitude of the
// input RGB is handled.
// --------------------------------------------------------------------------
class RGBAlbedoSpectrum {
public:
    RGBAlbedoSpectrum() = default;
    // `rgb` in [0, 1]^3; values outside that range are clamped. Suitable
    // for reflectance textures that ship as sRGB albedo.
    explicit RGBAlbedoSpectrum(const std::array<float, 3>& rgb);

    SampledSpectrum sample(const SampledWavelengths& wl) const;
    float evalAt(float lambda) const;

    std::array<float, 3> coeffs() const { return c_; }

private:
    std::array<float, 3> c_{};
};

class RGBUnboundedSpectrum {
public:
    RGBUnboundedSpectrum() = default;
    // `rgb` may contain values > 1 (e.g. HDR). A scale factor is
    // factored out; the remaining normalized RGB is looked up in the LUT.
    explicit RGBUnboundedSpectrum(const std::array<float, 3>& rgb);

    SampledSpectrum sample(const SampledWavelengths& wl) const;
    float evalAt(float lambda) const;

    float scale() const { return scale_; }
    std::array<float, 3> coeffs() const { return rsp_.coeffs(); }

private:
    float scale_ = 0.0f;
    RGBAlbedoSpectrum rsp_{};
};

class RGBIlluminantSpectrum {
public:
    RGBIlluminantSpectrum() = default;
    // `rgb` is interpreted as the desired tristimulus of an illuminant
    // relative to D65. sample() multiplies the upsampled reflectance by
    // the normalized D65 SPD.
    explicit RGBIlluminantSpectrum(const std::array<float, 3>& rgb);

    SampledSpectrum sample(const SampledWavelengths& wl) const;
    float evalAt(float lambda) const;

    float scale() const { return scale_; }
    std::array<float, 3> coeffs() const { return rsp_.coeffs(); }

private:
    float scale_ = 0.0f;
    RGBAlbedoSpectrum rsp_{};
};

}  // namespace astroray
