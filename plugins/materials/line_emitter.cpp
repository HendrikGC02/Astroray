#include "astroray/register.h"
#include "astroray/spectral.h"
#include "raytracer.h"

#include <algorithm>
#include <cmath>

namespace {

float gaussianLine(float wavelengthNm, float centerNm, float bandwidthNm) {
    float sigma = std::max(0.5f, bandwidthNm / 2.35482f);
    float x = (wavelengthNm - centerNm) / sigma;
    return std::exp(-0.5f * x * x);
}

Vec3 approximateLineRGB(float wavelengthNm, float bandwidthNm, float intensity) {
    double X = 0.0, Y = 0.0, Z = 0.0;
    constexpr float step = 2.0f;
    for (float lam = astroray::kLambdaMin; lam <= astroray::kLambdaMax; lam += step) {
        float spd = gaussianLine(lam, wavelengthNm, bandwidthNm) * intensity;
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

class LineEmitterPlugin : public Material {
    float wavelengthNm_;
    float bandwidthNm_;
    float intensity_;
    Vec3 emissionRgb_;

public:
    explicit LineEmitterPlugin(const astroray::ParamDict& p)
        : wavelengthNm_(std::clamp(p.getFloat("wavelength_nm", 532.0f),
                                   astroray::kLambdaMin, astroray::kLambdaMax)),
          bandwidthNm_(std::clamp(p.getFloat("bandwidth_nm", 8.0f), 0.5f, 100.0f)),
          intensity_(std::max(0.0f, p.getFloat("intensity", 1.0f))),
          emissionRgb_(approximateLineRGB(wavelengthNm_, bandwidthNm_, intensity_)) {}

    Vec3 emitted(const HitRecord& rec) const override {
        return rec.frontFace ? emissionRgb_ : Vec3(0.0f);
    }

    astroray::SampledSpectrum emittedSpectral(
            const HitRecord& rec,
            const astroray::SampledWavelengths& lambdas) const override {
        if (!rec.frontFace) return astroray::SampledSpectrum(0.0f);
        astroray::SampledSpectrum s;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            s[i] = gaussianLine(lambdas.lambda(i), wavelengthNm_, bandwidthNm_) * intensity_;
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

class LaserEmitterAliasPlugin : public LineEmitterPlugin {
public:
    explicit LaserEmitterAliasPlugin(const astroray::ParamDict& p)
        : LineEmitterPlugin(p) {}
};

ASTRORAY_REGISTER_MATERIAL("line_emitter", LineEmitterPlugin)
ASTRORAY_REGISTER_MATERIAL("laser_emitter", LaserEmitterAliasPlugin)
