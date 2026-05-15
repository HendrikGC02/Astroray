#pragma once

// DistantLight — sun-disk angular emitter (directional light from infinity).
//
// Models: distant sun with finite angular diameter. All rays arrive from the
// same direction ± small cone (determined by angularDiameter).
//
// Reference:
//   - Cycles kernel/light/distant.h::distant_light_sample (Apache-2.0).
//   - PBRT-v4 src/pbrt/lights.cpp::DistantLight (Apache-2.0).

#include "../light.h"
#include "../emission_spectrum.h"

namespace astroray {

class DistantLight : public Light {
public:
    // Constructor.
    // axis: normalized direction FROM the light (sun points along -axis).
    // angularDiameter: full angular width in radians (sun ≈ 0.53°).
    DistantLight(const Vec3& axis,
                 float angularDiameter,
                 const EmissionSpectrum& emission,
                 float intensity);

    // Light interface.
    void sampleLi(LiSample& result,
                  const Vec3& shadingPoint,
                  const Vec3& shadingNormal,
                  const SampledWavelengths& lambdas,
                  std::mt19937& gen) const override;

    float pdfLi(const Vec3& shadingPoint, const Vec3& direction) const override;

    float power() const override;

    AABB bounds() const override;

    OrientationCone orientationCone() const override;

private:
    Vec3             axis_;
    float            angularDiameter_;
    EmissionSpectrum emission_;
    float            intensity_;
    float            normalizeFactor_;
};

} // namespace astroray
