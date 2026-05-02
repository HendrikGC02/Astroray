#include "astroray/register.h"
#include "astroray/spectral.h"
#include "raytracer.h"

#include <algorithm>
#include <cmath>

namespace {

float relativeBlackbody(float wavelengthNm, float temperatureK) {
    if (temperatureK <= 0.0f) {
        return 0.0f;
    }
    float peakNm = std::clamp(2.897771955e6f / temperatureK,
                              astroray::kLambdaMin, astroray::kLambdaMax);
    double peak = planck(double(peakNm), double(temperatureK));
    if (peak <= 0.0 || !std::isfinite(peak)) {
        return 0.0f;
    }
    double v = planck(double(wavelengthNm), double(temperatureK)) / peak;
    return float(std::clamp(v, 0.0, 1.0));
}

Vec3 approximateBlackbodyRGB(float temperatureK, float intensity) {
    double X = 0.0, Y = 0.0, Z = 0.0;
    constexpr float step = 5.0f;
    for (float lam = astroray::kLambdaMin; lam <= astroray::kLambdaMax; lam += step) {
        float spd = relativeBlackbody(lam, temperatureK) * intensity;
        astroray::XYZ cmf = astroray::cieCmf1964_10deg(lam);
        X += double(spd * cmf.X * step);
        Y += double(spd * cmf.Y * step);
        Z += double(spd * cmf.Z * step);
    }
    Vec3 rgb = xyzToLinearSRGB(Vec3(float(X), float(Y), float(Z)));
    rgb = Vec3(std::max(0.0f, rgb.x), std::max(0.0f, rgb.y), std::max(0.0f, rgb.z));
    float maxC = std::max({rgb.x, rgb.y, rgb.z, 1e-6f});
    return rgb * (intensity / maxC);
}

} // namespace

class BlackbodyEmitterPlugin : public Material {
    float temperatureK_;
    float intensity_;
    Vec3 emissionRgb_;

public:
    explicit BlackbodyEmitterPlugin(const astroray::ParamDict& p)
        : temperatureK_(std::clamp(p.getFloat("temperature_kelvin", 6500.0f), 500.0f, 40000.0f)),
          intensity_(std::max(0.0f, p.getFloat("intensity", 1.0f))),
          emissionRgb_(approximateBlackbodyRGB(temperatureK_, intensity_)) {}

    Vec3 emitted(const HitRecord& rec) const override {
        return rec.frontFace ? emissionRgb_ : Vec3(0.0f);
    }

    astroray::SampledSpectrum emittedSpectral(
            const HitRecord& rec,
            const astroray::SampledWavelengths& lambdas) const override {
        if (!rec.frontFace) return astroray::SampledSpectrum(0.0f);
        astroray::SampledSpectrum s;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            s[i] = relativeBlackbody(lambdas.lambda(i), temperatureK_) * intensity_;
        }
        return s;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
    }

    Vec3 getEmission() const override { return emissionRgb_; }
    bool isEmissive() const override { return true; }
};

class BlackbodyAliasPlugin : public BlackbodyEmitterPlugin {
public:
    explicit BlackbodyAliasPlugin(const astroray::ParamDict& p)
        : BlackbodyEmitterPlugin(p) {}
};

ASTRORAY_REGISTER_MATERIAL("blackbody", BlackbodyEmitterPlugin)
ASTRORAY_REGISTER_MATERIAL("blackbody_emitter", BlackbodyAliasPlugin)
