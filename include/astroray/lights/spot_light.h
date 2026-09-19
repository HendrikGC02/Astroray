#pragma once

// SpotLight — directional cone light with optional IES profile.
//
// Emission profile (pkg89 research §5.2):
//   - Inner cone (θ ≤ innerAngle): full intensity.
//   - Transition (innerAngle < θ ≤ outerAngle): smooth falloff (cos² or linear).
//   - Outside outer cone: zero.
//
// Reference:
//   - Cycles kernel/light/spot.h::spot_light_sample (Apache-2.0).
//   - PBRT-v4 src/pbrt/lights.cpp::SpotLight (Apache-2.0).

#include "../light.h"
#include "../emission_spectrum.h"
#include "../../raytracer.h"  // for IESProfile

namespace astroray {

class SpotLight : public Light {
public:
    // Constructor.
    // axis: normalized direction the spot points.
    // innerAngle, outerAngle: cone half-angles (radians), inner ≤ outer.
    // radius: soft-shadow radius (0 = point source).
    // ies: optional IES candela profile (nullptr = smooth falloff).
    SpotLight(const Vec3& position,
              const Vec3& axis,
              float innerAngle,
              float outerAngle,
              const EmissionSpectrum& emission,
              float intensity,
              float radius = 0.0f,
              const IESProfile* ies = nullptr);

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

    bool fillDeviceParams(DeviceLightParams& out) const override;  // pkg89-GPU

    // pkg276: the light object's frame (matrix_world 3x3 columns: local X, Y, Z
    // in world) for the IES lookup; Cycles evaluates IES in light-local space
    // (kernel/svm/ies.h). Without it a default frame is derived (see ctor).
    void setIESFrame(const Vec3& fx, const Vec3& fy, const Vec3& fz) {
        iesFx_ = fx; iesFy_ = fy; iesFz_ = fz;
    }

private:
    Vec3             position_;
    Vec3             axis_;
    float            innerAngle_;
    float            outerAngle_;
    EmissionSpectrum emission_;
    float            intensity_;
    float            radius_;
    const IESProfile* ies_;
    float            normalizeFactor_;
    Vec3             iesFx_, iesFy_, iesFz_;  // pkg276 IES frame

    // Helper: compute falloff for angle θ from axis.
    float angleFalloff(float cosTheta) const;
};

} // namespace astroray
