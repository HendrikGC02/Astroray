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

void BackgroundLight::sampleLi(LiSample& sample,
                               const Vec3& shadingPoint,
                               const Vec3& shadingNormal,
                               const SampledWavelengths& lambdas,
                               std::mt19937& gen) const {
    // pkg258: importance-sample the HDRI CDF (EnvironmentMap::sample, the same
    // estimator pathTraceSpectral's env-NEE leg uses). Reference: Cycles
    // background_light_sample / PBRT 4e §12.5 ImageInfiniteLight::SampleLi.
    (void)shadingNormal;
    EnvironmentMap::EnvSample es = envMap_->sample(gen);

    Vec3 wi = es.direction;
    // Infinite-distance light: place the "position" far along wi so callers that
    // derive a direction from (position - shadingPoint) recover wi, and report an
    // infinite distance so the shadow ray runs to infinity.
    sample.position = shadingPoint + wi * 1e6f;
    sample.normal   = -wi;
    sample.distance = std::numeric_limits<float>::max();

    // Spectral radiance from evalSpectral(wi) — bilinear, strength+tint applied —
    // so this matches the env-NEE/miss legs per wavelength. emission_rgb keeps the
    // point-sample RGB for ReSTIR compatibility.
    sample.emission_spec = envMap_->evalSpectral(wi, lambdas);
    sample.emission_rgb  = es.radiance;

    sample.pdf     = es.pdf;   // solid-angle pdf, 1/sr
    sample.isDelta = false;    // area/environment light, not a delta direction
}

float BackgroundLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    // pkg258: exact solid-angle pdf of the HDRI CDF for `direction` (the MIS
    // partner of BSDF sampling). Cycles background_light_pdf.
    (void)shadingPoint;
    return envMap_->pdf(direction);
}

float BackgroundLight::power() const {
    // pkg258: approximate radiant power as the solid-angle integral of radiance
    // over the sphere, L̄·4π. totalPower = Σ_{u,v} luminance·sinθ_v; the lat-long
    // per-texel solid angle is ΔΩ = sinθ·(π/H)·(2π/W), so ∫L dω ≈ totalPower·
    // 2π²/(W·H), then scaled by strength. Nothing consumes this today (pkg86 owns
    // light-tree inclusion); it is a monotone energy proxy, not a calibrated value.
    int w = envMap_->getWidth(), h = envMap_->getHeight();
    if (w == 0 || h == 0) return 0.0f;
    const float twoPi2 = 2.0f * static_cast<float>(M_PI) * static_cast<float>(M_PI);
    return envMap_->getTotalPower() * twoPi2 / (static_cast<float>(w) * h)
           * envMap_->getStrength();
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
