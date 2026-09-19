#pragma once

// PointLight — isotropic point light with optional soft-shadow radius and IES profile.
//
// Fixes: Blender POINT lights are currently faked as 0.1 m emissive spheres
// (pkg89 research §1.2). This provides correct 1/r² falloff, correct PDF,
// and optional IES candela distribution (pkg89 Q12: IES on PointLight + SpotLight).
//
// Reference:
//   - Cycles kernel/light/point.h::point_light_sample (Apache-2.0).
//   - PBRT-v4 src/pbrt/lights.cpp::PointLight (Apache-2.0).

#include "../light.h"
#include "../emission_spectrum.h"
#include "../../raytracer.h"  // for IESProfile

namespace astroray {

class PointLight : public Light {
public:
    // Constructor.
    // radius: soft-shadow radius (0 = hard shadows, singularity at center).
    // ies: optional IES candela profile (nullptr = isotropic).
    PointLight(const Vec3& position,
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
    EmissionSpectrum emission_;
    float            intensity_;
    float            radius_;
    const IESProfile* ies_;       // not owned
    float            normalizeFactor_;
    Vec3             iesFx_, iesFy_, iesFz_;  // pkg276 IES frame
};

} // namespace astroray
