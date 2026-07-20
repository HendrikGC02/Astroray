#pragma once

// AreaLight — planar area light (rectangle / disk / ellipse) with spread cone.
//
// Emission profile (pkg89 research §5.4):
//   - Lambertian base (cosine falloff from surface normal).
//   - Optional "spread" cone: emission restricted to θ ≤ spread_angle.
//
// Shapes: rectangle, disk, ellipse (Cycles convention).
//
// Reference:
//   - Cycles kernel/light/area.h::area_light_sample (Apache-2.0).
//   - PBRT-v4 src/pbrt/lights.cpp::DiffuseAreaLight (Apache-2.0).

#include "../light.h"
#include "../emission_spectrum.h"

namespace astroray {

class AreaLight : public Light {
public:
    enum class Shape { Rectangle, Disk, Ellipse };

    // Constructor.
    // position: center of the area light (world space).
    // u, v: orthonormal axes defining the plane (width, height).
    // width, height: size along u, v (for Rectangle/Ellipse; Disk uses width as radius).
    // shape: Rectangle (default), Disk, Ellipse.
    // spread: emission cone half-angle in radians (π/2 = Lambertian hemisphere).
    AreaLight(const Vec3& position,
              const Vec3& u,
              const Vec3& v,
              float width,
              float height,
              Shape shape,
              const EmissionSpectrum& emission,
              float intensity,
              float spread = static_cast<float>(M_PI) / 2.0f);

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

private:
    Vec3             position_;
    Vec3             u_, v_, normal_;  // u × v = normal
    float            width_, height_;
    Shape            shape_;
    EmissionSpectrum emission_;
    float            intensity_;
    float            spread_;
    float            area_;            // cached at construction (Q2 resolution)
    float            normalizeFactor_;

    // Helper: sample a point on the shape (uniform area sampling).
    Vec3 sampleSurface(std::mt19937& gen) const;

    // Helper: check if angle from normal is within spread cone.
    bool withinSpread(const Vec3& direction) const;
};

} // namespace astroray
