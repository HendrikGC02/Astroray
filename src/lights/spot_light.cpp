// NOTE: raytracer.h must come BEFORE light headers (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/spot_light.h"
#include "astroray/spectrum.h"
#include "raytracer.h"  // for Vec3, IESProfile
#include <cmath>
#include <algorithm>
#include <random>

// Reference: Cycles kernel/light/spot.h::spot_light_sample (Apache-2.0).

namespace astroray {

SpotLight::SpotLight(const Vec3& position,
                      const Vec3& axis,
                      float innerAngle,
                      float outerAngle,
                      const EmissionSpectrum& emission,
                      float intensity,
                      float radius,
                      const IESProfile* ies)
    : position_(position)
    , axis_(axis.normalized())
    , innerAngle_(innerAngle)
    , outerAngle_(outerAngle)
    , emission_(emission)
    , intensity_(intensity)
    , radius_(radius)
    , ies_(ies)
{
    // Compute normalize factor using geometric normalization (Cycles parity).
    // For point/spot lights, pass area=1.0 (normalize factor is just 1/pi).
    normalizeFactor_ = Light::computeNormalizeFactor(1.0f, true);
}

void SpotLight::sampleLi(LiSample& sample,
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
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float u1 = dist(gen);
        float u2 = dist(gen);
        float z = 1.0f - 2.0f * u1;
        float r = std::sqrt(std::max(0.0f, 1.0f - z * z));
        float phi = 2.0f * static_cast<float>(M_PI) * u2;
        Vec3 offset(r * std::cos(phi), r * std::sin(phi), z);
        sampledPos = position_ + offset * radius_;

        lightToShading = shadingPoint - sampledPos;
        distance = lightToShading.length();
        lightDir = lightToShading / distance;
    }

    sample.position = sampledPos;
    sample.normal = -lightDir;
    sample.distance = distance;

    // Check cone constraint.
    float cosTheta = lightDir.dot(axis_);
    float angleFromAxis = std::acos(std::clamp(cosTheta, -1.0f, 1.0f));
    if (angleFromAxis > outerAngle_) {
        // Outside cone: zero emission.
        sample.emission_spec = SampledSpectrum(0.0f);
        sample.emission_rgb = Vec3(0);
        sample.pdf = 0.0f;
        return;
    }

    // Angle falloff (smooth transition from inner to outer cone).
    float angleFalloffFactor = angleFalloff(cosTheta);

    // 1/r² falloff.
    float falloff = 1.0f / (distance * distance);

    // IES profile modulation (if present).
    float iesModulation = 1.0f;
    if (ies_ != nullptr) {
        iesModulation = ies_->sample(axis_, lightDir);
    }

    // Evaluate spectral emission.
    // pkg122: a Blender spot light is a point light of power P masked by the
    // cone, so it carries the same radiant intensity I = P/(4π) as the point
    // light (Cycles kernel/light/spot.h inherits spot.eval_fac from the point
    // path). The prior 1/π was 4× too large. Apache-2.0.
    constexpr float kInvFourPiF = 0.07957747155f;  // 1/(4π)
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    emissionSpec *= (intensity_ * kInvFourPiF * falloff * angleFalloffFactor * iesModulation);

    sample.emission_spec = emissionSpec;

    // Convert to RGB.
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    sample.emission_rgb = Vec3(
        3.2404542f * xyz.X - 1.5371385f * xyz.Y - 0.4985314f * xyz.Z,
        -0.9692660f * xyz.X + 1.8760108f * xyz.Y + 0.0415560f * xyz.Z,
        0.0556434f * xyz.X - 0.2040259f * xyz.Y + 1.0572252f * xyz.Z
    );

    // pkg122: a radius-0 spot is a DELTA light (single direction to the source),
    // so pdf = 1 like the point light — the 1/d² falloff and cone attenuation are
    // already baked into emission. The prior 1/coneSolidAngle made the L/pdf
    // divide multiply brightness by the cone solid angle (cone-angle-dependent
    // over-bright). For radius>0 the sphere emitter uses uniform-surface pdf
    // 1/(4π·r²), matching the point sphere light (Cycles spot inherits point).
    if (radius_ > 0.0f) {
        sample.pdf = 1.0f / (4.0f * static_cast<float>(M_PI) * radius_ * radius_);
    } else {
        sample.pdf = 1.0f;
    }
}

float SpotLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    float cosTheta = direction.dot(axis_);
    float angleFromAxis = std::acos(std::clamp(cosTheta, -1.0f, 1.0f));
    if (angleFromAxis > outerAngle_) {
        return 0.0f;
    }

    // pkg122: mirror sampleLi's measure — radius-0 is a delta light (return 0,
    // "not useful for MIS", like PointLight::pdfLi); radius>0 uses 1/(4π·r²).
    if (radius_ > 0.0f) {
        return 1.0f / (4.0f * static_cast<float>(M_PI) * radius_ * radius_);
    } else {
        return 0.0f;
    }
}

float SpotLight::power() const {
    // Power estimate: integrate emission over the cone solid angle.
    SampledWavelengths lambdas = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    float luminance = xyz.Y;
    float coneSolidAngle = 2.0f * static_cast<float>(M_PI) * (1.0f - std::cos(outerAngle_));
    return luminance * intensity_ * normalizeFactor_ * coneSolidAngle;
}

AABB SpotLight::bounds() const {
    Vec3 r(radius_, radius_, radius_);
    return AABB(position_ - r, position_ + r);
}

OrientationCone SpotLight::orientationCone() const {
    return OrientationCone::fromAxisAngle(axis_, outerAngle_);
}

// Helper: compute falloff for angle θ from axis.
// Smooth transition from inner (full intensity) to outer (zero).
// Reference: Cycles intern/cycles/kernel/light/spot.h::spot_light_attenuation
// and intern/cycles/util/math_base.h::smoothstepf (Apache-2.0).
float SpotLight::angleFalloff(float cosTheta) const {
    float cosOuter = std::cos(outerAngle_);
    float cosInner = std::cos(innerAngle_);

    if (cosTheta >= cosInner) {
        return 1.0f;  // inside inner cone
    }
    if (cosTheta <= cosOuter) {
        return 0.0f;  // outside outer cone
    }

    // Cycles cubic Hermite smoothstep: 3t² - 2t³ (zero derivative at endpoints).
    float t = (cosTheta - cosOuter) / (cosInner - cosOuter);
    return t * t * (3.0f - 2.0f * t);
}

// pkg89-GPU / GAP 1 — device upload description mirroring sampleLi() radiometry.
bool SpotLight::fillDeviceParams(DeviceLightParams& out) const {
    out.kind     = DeviceLightParams::Spot;
    out.position = position_;
    out.axis     = axis_;
    out.radius   = radius_;
    out.cosInner = std::cos(innerAngle_);
    out.cosOuter = std::cos(outerAngle_);
    emission_.deviceReference(out.emissionRGB, out.exactIlluminant);
    // pkg218: baked device SPD for non-RGB emission modes (see point_light.cpp).
    if (!out.exactIlluminant) out.emissionProfileSamples = emission_.bakeDeviceProfile();
    // pkg122: staticScale = intensity·(1/(4π)) = I = P/(4π), matching sampleLi.
    constexpr float kInvFourPiF = 0.07957747155f;  // 1/(4π)
    out.staticScale = intensity_ * kInvFourPiF;
    // NOTE: IES modulation not mirrored on the GPU in v1 (follow-up).
    return true;
}

} // namespace astroray
