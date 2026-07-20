// NOTE: raytracer.h must come BEFORE light headers (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/point_light.h"
#include "astroray/spectrum.h"
#include "raytracer.h"  // for Vec3, IESProfile
#include <cmath>
#include <random>
#include <limits>

// Reference: Cycles kernel/light/point.h::point_light_sample (Apache-2.0).

namespace astroray {

PointLight::PointLight(const Vec3& position,
                        const EmissionSpectrum& emission,
                        float intensity,
                        float radius,
                        const IESProfile* ies)
    : position_(position)
    , emission_(emission)
    , intensity_(intensity)
    , radius_(radius)
    , ies_(ies)
{
    // Compute normalize factor using geometric normalization (Cycles parity).
    // For point lights, pass area=1.0 (normalize factor is just 1/pi).
    normalizeFactor_ = Light::computeNormalizeFactor(1.0f, true);
}

void PointLight::sampleLi(LiSample& sample,
                          const Vec3& shadingPoint,
                          const Vec3& shadingNormal,
                          const SampledWavelengths& lambdas,
                          std::mt19937& gen) const {
    // Direction from shading point to light center.
    Vec3 lightToShading = shadingPoint - position_;
    float distance = lightToShading.length();
    Vec3 lightDir = lightToShading / distance;

    // Soft-shadow sampling: if radius > 0, sample a point on the sphere surface.
    Vec3 sampledPos = position_;
    if (radius_ > 0.0f) {
        // Uniform sphere surface sampling.
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float u1 = dist(gen);
        float u2 = dist(gen);
        float z = 1.0f - 2.0f * u1;
        float r = std::sqrt(std::max(0.0f, 1.0f - z * z));
        float phi = 2.0f * static_cast<float>(M_PI) * u2;
        Vec3 offset(r * std::cos(phi), r * std::sin(phi), z);
        sampledPos = position_ + offset * radius_;

        // Recompute direction and distance to sampled point.
        lightToShading = shadingPoint - sampledPos;
        distance = lightToShading.length();
        lightDir = lightToShading / distance;
    }

    sample.position = sampledPos;
    sample.normal = -lightDir;  // normal points outward from light
    sample.distance = distance;

    // 1/r² falloff.
    float falloff = 1.0f / (distance * distance);

    // IES profile modulation (if present).
    float iesModulation = 1.0f;
    if (ies_ != nullptr) {
        // IESProfile::sample expects (axis, directionFromLight).
        // For PointLight, use a default downward axis (-Y).
        Vec3 axis(0, -1, 0);
        iesModulation = ies_->sample(axis, lightDir);
    }

    // Evaluate spectral emission.
    // Reference: Cycles intern/cycles/scene/light.cpp:127-131 (eval_fac = invarea * M_1_PI_F, Apache-2.0).
    constexpr float kM1PiF = 0.31830988618f;  // M_1_PI_F = 1/π
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    emissionSpec *= (intensity_ * normalizeFactor_ * kM1PiF * falloff * iesModulation);

    sample.emission_spec = emissionSpec;

    // Convert to RGB for ReSTIR compatibility.
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    sample.emission_rgb = Vec3(
        3.2404542f * xyz.X - 1.5371385f * xyz.Y - 0.4985314f * xyz.Z,
        -0.9692660f * xyz.X + 1.8760108f * xyz.Y + 0.0415560f * xyz.Z,
        0.0556434f * xyz.X - 0.2040259f * xyz.Y + 1.0572252f * xyz.Z
    );

    // PDF: for radius = 0 (point source), PDF is delta (represented as 1.0 here).
    // For radius > 0, PDF is uniform over sphere surface: 1 / (4π r²).
    if (radius_ > 0.0f) {
        sample.pdf = 1.0f / (4.0f * static_cast<float>(M_PI) * radius_ * radius_);
    } else {
        sample.pdf = 1.0f;
    }
}

float PointLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    if (radius_ > 0.0f) {
        return 1.0f / (4.0f * static_cast<float>(M_PI) * radius_ * radius_);
    } else {
        // Delta distribution: PDF is technically infinite, but we return 0
        // here to signal "not useful for MIS" (the integrator handles delta lights separately).
        return 0.0f;
    }
}

float PointLight::power() const {
    // Total emitted power: integrate emission over all directions.
    // For an isotropic point light, power ~ intensity × (4π steradians).
    // We approximate by sampling emission at D65-like wavelengths and converting to luminance.
    SampledWavelengths lambdas = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    float luminance = xyz.Y;  // photopic luminance
    return luminance * intensity_ * normalizeFactor_ * 4.0f * static_cast<float>(M_PI);
}

AABB PointLight::bounds() const {
    // Point light has negligible spatial extent (or small sphere for soft shadows).
    Vec3 r(radius_, radius_, radius_);
    return AABB(position_ - r, position_ + r);
}

OrientationCone PointLight::orientationCone() const {
    // Isotropic emission (or IES-modulated isotropic).
    // pkg89 Q12: IES on PointLight widens to full-sphere cone.
    return OrientationCone::fullSphere();
}

// pkg89-GPU / GAP 1 — device upload description mirroring sampleLi() radiometry.
bool PointLight::fillDeviceParams(DeviceLightParams& out) const {
    out.kind     = DeviceLightParams::Point;
    out.position = position_;
    out.radius   = radius_;
    emission_.deviceReference(out.emissionRGB, out.exactIlluminant);
    // staticScale = intensity·invarea·(1/π); invarea == normalizeFactor_ (==1 for point).
    // Matches sampleLi: emissionSpec *= intensity_ * normalizeFactor_ * kM1PiF * falloff.
    constexpr float kM1PiF = 0.31830988618f;
    out.staticScale = intensity_ * normalizeFactor_ * kM1PiF;
    // NOTE: IES modulation is not mirrored on the GPU in v1; an IES PointLight
    // renders isotropic on the device (documented follow-up). Non-IES parity exact.
    return true;
}

} // namespace astroray
