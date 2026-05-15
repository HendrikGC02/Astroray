// NOTE: raytracer.h must come BEFORE light headers (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/distant_light.h"
#include "astroray/spectrum.h"
#include "raytracer.h"  // for Vec3, buildOrthonormalBasis
#include <cmath>
#include <random>
#include <limits>

// Reference: Cycles kernel/light/distant.h::distant_light_sample (Apache-2.0).

namespace astroray {

DistantLight::DistantLight(const Vec3& axis,
                            float angularDiameter,
                            const EmissionSpectrum& emission,
                            float intensity)
    : axis_(axis.normalized())
    , angularDiameter_(angularDiameter)
    , emission_(emission)
    , intensity_(intensity)
    , normalizeFactor_(Light::computeNormalizeFactor(emission, normalize))
{
}

Light::LiSample DistantLight::sampleLi(const Vec3& shadingPoint,
                                        const Vec3& shadingNormal,
                                        const SampledWavelengths& lambdas,
                                        std::mt19937& gen) const {
    LiSample sample;

    // Distant light: rays arrive from a fixed direction (axis points FROM light).
    // Sample a direction within the angular disk.
    Vec3 dir = -axis_;  // direction TO light
    if (angularDiameter_ > 0.0f) {
        // Uniform disk sampling within half-angle cone.
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float u1 = dist(gen);
        float u2 = dist(gen);
        float halfAngle = angularDiameter_ / 2.0f;
        float r = std::sqrt(u1) * std::sin(halfAngle);
        float phi = 2.0f * static_cast<float>(M_PI) * u2;

        // Build orthonormal basis around -axis.
        Vec3 w = -axis_;
        Vec3 u = (std::abs(w.x) > 0.1f ? Vec3(0, 1, 0) : Vec3(1, 0, 0)).cross(w).normalized();
        Vec3 v = w.cross(u);

        // Perturb direction within cone.
        dir = (w + u * (r * std::cos(phi)) + v * (r * std::sin(phi))).normalized();
    }

    sample.position = shadingPoint + dir * 1e6f;  // far away (simulates infinity)
    sample.normal = -dir;
    sample.distance = std::numeric_limits<float>::max();

    // Evaluate spectral emission.
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    emissionSpec *= (intensity_ * normalizeFactor_);

    sample.emission_spec = emissionSpec;

    // Convert to RGB.
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    sample.emission_rgb = Vec3(
        3.2404542f * xyz.X - 1.5371385f * xyz.Y - 0.4985314f * xyz.Z,
        -0.9692660f * xyz.X + 1.8760108f * xyz.Y + 0.0415560f * xyz.Z,
        0.0556434f * xyz.X - 0.2040259f * xyz.Y + 1.0572252f * xyz.Z
    );

    // PDF: 1 / solid angle of the disk.
    float halfAngle = angularDiameter_ / 2.0f;
    float solidAngle = 2.0f * static_cast<float>(M_PI) * (1.0f - std::cos(halfAngle));
    sample.pdf = 1.0f / solidAngle;

    return sample;
}

float DistantLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    float halfAngle = angularDiameter_ / 2.0f;
    float solidAngle = 2.0f * static_cast<float>(M_PI) * (1.0f - std::cos(halfAngle));
    return 1.0f / solidAngle;
}

float DistantLight::power() const {
    // Distant light: power is proportional to solid angle × intensity.
    SampledWavelengths lambdas = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    float luminance = xyz.Y;
    float halfAngle = angularDiameter_ / 2.0f;
    float solidAngle = 2.0f * static_cast<float>(M_PI) * (1.0f - std::cos(halfAngle));
    return luminance * intensity_ * normalizeFactor_ * solidAngle;
}

AABB DistantLight::bounds() const {
    // Infinite light: unbounded AABB.
    return AABB(Vec3(-std::numeric_limits<float>::max()),
                Vec3(std::numeric_limits<float>::max()));
}

OrientationCone DistantLight::orientationCone() const {
    float halfAngle = angularDiameter_ / 2.0f;
    return OrientationCone::fromAxisAngle(-axis_, halfAngle);
}

} // namespace astroray
