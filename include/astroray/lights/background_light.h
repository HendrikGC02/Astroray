#pragma once

// BackgroundLight — environment map (infinite-distance envmap CDF sampling).
//
// Wraps an EnvironmentMap (pkg14) and exposes it as a dedicated Light.
// Coexists with DistantLight (pkg89 Q4: sun + sky needs both).
//
// Reference:
//   - Cycles kernel/light/background.h::background_light_sample (Apache-2.0).
//   - PBRT-v4 src/pbrt/lights.cpp::InfiniteAreaLight (Apache-2.0).

#include "../light.h"
#include "../../raytracer.h"  // for EnvironmentMap

namespace astroray {

class BackgroundLight : public Light {
public:
    // Constructor.
    // envMap: not owned (lifetime managed by RayTracer / scene).
    explicit BackgroundLight(const EnvironmentMap* envMap);

    // Light interface.
    LiSample sampleLi(const Vec3& shadingPoint,
                       const Vec3& shadingNormal,
                       const SampledWavelengths& lambdas,
                       std::mt19937& gen) const override;

    float pdfLi(const Vec3& shadingPoint, const Vec3& direction) const override;

    float power() const override;

    AABB bounds() const override;

    OrientationCone orientationCone() const override;

private:
    const EnvironmentMap* envMap_;  // not owned
};

} // namespace astroray
