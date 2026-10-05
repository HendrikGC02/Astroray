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

    // pkg181: BSDF-ray intersection (Cycles distant/sun-disk parity). A ray
    // "hits" the sun when its direction lies within the angular-disk half-angle
    // of -axis_; hittable only when angularDiameter_ > 0 (true delta stays NEE).
    bool intersect(const Vec3& rayOrigin, const Vec3& rayDir,
                   float tMin, float tMax,
                   const SampledWavelengths& lambdas,
                   Intersection& out) const override;

    float power() const override;
    float treeEnergy() const override;  // #859: strength, as Cycles

    AABB bounds() const override;

    OrientationCone orientationCone() const override;

    bool fillDeviceParams(DeviceLightParams& out) const override;  // pkg89-GPU

    // #946: Nishita sky-sun disc profile. Cycles draws the sun disc (svm/sky.h
    // sky_radiance_nishita, Apache-2.0) as
    //   L = mix(pixel_bottom, pixel_top, y) * limb,
    //   y = (elevation(dir) - sun_elevation) / angular_diameter + 0.5,
    //   limb = 1 - 0.6 * (1 - sqrt(1 - (angle_to_sun / half_angular)^2)),
    // so a low sun is redder/dimmer at its lower limb. A ray hitting this lamp
    // (camera or BSDF ray; NEE keeps the uniform mean) sees that profile.
    // `bottomRGB`/`topRGB` are RELATIVE colours, pixel_{bottom,top}/lum(mean):
    // their mean is the lamp's emission colour, so the disc average (limb mean
    // 0.8) equals the NEE radiance S/Omega. World +Z is up (Blender world).
    void setDiscProfile(const Vec3& bottomRGB, const Vec3& topRGB);

private:
    Vec3             axis_;
    float            angularDiameter_;
    EmissionSpectrum emission_;
    float            intensity_;
    float            normalizeFactor_;
    Vec3             refRGB_;  // #878: wavelength-independent emission RGB
    bool             hasDiscProfile_ = false;  // #946
    Vec3             discBottomRGB_, discTopRGB_;
    EmissionSpectrum discBottom_, discTop_;
};

} // namespace astroray
