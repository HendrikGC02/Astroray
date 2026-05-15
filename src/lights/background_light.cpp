// NOTE: raytracer.h must come BEFORE light headers (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/background_light.h"
#include "astroray/spectrum.h"
#include "raytracer.h"  // for Vec3, EnvironmentMap, AABB
#include <cmath>
#include <limits>

// Reference: Cycles kernel/light/background.h::background_light_sample (Apache-2.0).

namespace astroray {

BackgroundLight::BackgroundLight(const EnvironmentMap* envMap)
    : envMap_(envMap)
{
}

Light::LiSample BackgroundLight::sampleLi(const Vec3& shadingPoint,
                                           const Vec3& shadingNormal,
                                           const SampledWavelengths& lambdas,
                                           std::mt19937& gen) const {
    LiSample sample;

    // BackgroundLight wraps EnvironmentMap. The EnvironmentMap::sample method
    // already performs importance sampling via marginal CDF.
    // For Phase A, we provide a simple uniform-sphere sampling stub.
    // Full integration with EnvironmentMap::sample is deferred to Phase B or
    // when the EnvironmentMap API is extended to support spectral queries.

    // Uniform sphere sampling (placeholder).
    std::uniform_real_distribution<float> dist(0.0f, 1.0f);
    float u1 = dist(gen);
    float u2 = dist(gen);
    float z = 1.0f - 2.0f * u1;
    float r = std::sqrt(std::max(0.0f, 1.0f - z * z));
    float phi = 2.0f * static_cast<float>(M_PI) * u2;
    Vec3 dir(r * std::cos(phi), r * std::sin(phi), z);

    sample.position = shadingPoint + dir * 1e6f;  // far away
    sample.normal = -dir;
    sample.distance = std::numeric_limits<float>::max();

    // Query EnvironmentMap for RGB emission.
    // NOTE: EnvironmentMap::lookup currently returns RGB only. Spectral
    // upsampling is a temporary workaround until EnvironmentMap is extended.
    Vec3 emissionRGB = envMap_->lookup(dir);

    // Upsample RGB to spectral via RGBIlluminantSpectrum.
    RGBIlluminantSpectrum rgbSpectrum({emissionRGB.x, emissionRGB.y, emissionRGB.z});
    sample.emission_spec = rgbSpectrum.sample(lambdas);
    sample.emission_rgb = emissionRGB;

    // PDF: 1 / (4π) for uniform sphere sampling.
    sample.pdf = 1.0f / (4.0f * static_cast<float>(M_PI));

    return sample;
}

float BackgroundLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    // Uniform sphere PDF.
    return 1.0f / (4.0f * static_cast<float>(M_PI));
}

float BackgroundLight::power() const {
    // Background light power: integrate envmap over all directions.
    // Approximate by average luminance × 4π.
    // This is a placeholder; accurate computation requires envmap CDF traversal.
    return 1.0f;  // stub value
}

AABB BackgroundLight::bounds() const {
    // Infinite light: unbounded.
    return AABB(Vec3(-std::numeric_limits<float>::max()),
                Vec3(std::numeric_limits<float>::max()));
}

OrientationCone BackgroundLight::orientationCone() const {
    // Isotropic (full sphere).
    return OrientationCone::fullSphere();
}

} // namespace astroray
