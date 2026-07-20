// NOTE: raytracer.h must come BEFORE area_light.h (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/area_light.h"
#include "astroray/spectrum.h"
#include <cmath>
#include <algorithm>
#include <random>

// Reference: Cycles kernel/light/area.h::area_light_sample (Apache-2.0).

namespace astroray {

AreaLight::AreaLight(const Vec3& position,
                      const Vec3& u,
                      const Vec3& v,
                      float width,
                      float height,
                      Shape shape,
                      const EmissionSpectrum& emission,
                      float intensity,
                      float spread)
    : position_(position)
    , u_(u.normalized())
    , v_(v.normalized())
    , width_(width)
    , height_(height)
    , shape_(shape)
    , emission_(emission)
    , intensity_(intensity)
    , spread_(spread)
{
    // Compute normal (u × v).
    normal_ = u_.cross(v_).normalized();

    // Cache area at construction (pkg89 Q2 resolution).
    switch (shape_) {
        case Shape::Rectangle:
            area_ = width_ * height_;
            break;
        case Shape::Disk:
            area_ = static_cast<float>(M_PI) * width_ * width_;  // width is radius
            break;
        case Shape::Ellipse:
            area_ = static_cast<float>(M_PI) * width_ * height_;
            break;
    }

    // Compute normalize factor using geometric normalization (Cycles parity).
    normalizeFactor_ = Light::computeNormalizeFactor(area_, true);
}

void AreaLight::sampleLi(LiSample& sample,
                         const Vec3& shadingPoint,
                         const Vec3& shadingNormal,
                         const SampledWavelengths& lambdas,
                         std::mt19937& gen) const {
    // Sample a point on the area light surface.
    Vec3 sampledPos = sampleSurface(gen);
    sample.position = sampledPos;
    sample.normal = normal_;

    // Direction from sampled point to shading point.
    Vec3 lightToShading = shadingPoint - sampledPos;
    float distance = lightToShading.length();
    Vec3 dir = lightToShading / distance;

    sample.distance = distance;

    // Check spread cone constraint.
    float cosTheta = dir.dot(normal_);
    if (!withinSpread(dir) || cosTheta <= 0.0f) {
        // Outside emission cone or back-facing: zero emission.
        sample.emission_spec = SampledSpectrum(0.0f);
        sample.emission_rgb = Vec3(0);
        sample.pdf = 0.0f;
        return;
    }

    // Lambertian cosine falloff.
    float cosFalloff = cosTheta;

    // Geometric term: convert area measure to solid angle.
    float distSq = distance * distance;
    float geometricFactor = cosFalloff / distSq;

    // Evaluate spectral emission.
    // Reference: Cycles intern/cycles/scene/light.cpp:127-131 (eval_fac = invarea * M_1_PI_F, Apache-2.0).
    constexpr float kM1PiF = 0.31830988618f;  // M_1_PI_F = 1/π
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    emissionSpec *= (intensity_ * normalizeFactor_ * kM1PiF * geometricFactor);

    sample.emission_spec = emissionSpec;

    // Convert to RGB.
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    sample.emission_rgb = Vec3(
        3.2404542f * xyz.X - 1.5371385f * xyz.Y - 0.4985314f * xyz.Z,
        -0.9692660f * xyz.X + 1.8760108f * xyz.Y + 0.0415560f * xyz.Z,
        0.0556434f * xyz.X - 0.2040259f * xyz.Y + 1.0572252f * xyz.Z
    );

    // PDF: 1 / area (uniform area sampling).
    sample.pdf = 1.0f / area_;
}

float AreaLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    // PDF for area light: 1 / area, converted to solid angle measure.
    // This is a simplified version; full MIS requires ray-triangle intersection.
    return 1.0f / area_;
}

float AreaLight::power() const {
    // Power: integrate emission over area and hemisphere.
    // For Lambertian emission over hemisphere: π × area × intensity.
    SampledWavelengths lambdas = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    float luminance = xyz.Y;
    return luminance * intensity_ * normalizeFactor_ * area_ * static_cast<float>(M_PI);
}

AABB AreaLight::bounds() const {
    // Bounding box of the area light shape.
    Vec3 corners[4];
    switch (shape_) {
        case Shape::Rectangle:
            corners[0] = position_ - u_ * (width_ / 2.0f) - v_ * (height_ / 2.0f);
            corners[1] = position_ + u_ * (width_ / 2.0f) - v_ * (height_ / 2.0f);
            corners[2] = position_ - u_ * (width_ / 2.0f) + v_ * (height_ / 2.0f);
            corners[3] = position_ + u_ * (width_ / 2.0f) + v_ * (height_ / 2.0f);
            break;
        case Shape::Disk:
        case Shape::Ellipse:
            // Approximate bounding box from extents.
            corners[0] = position_ - u_ * width_ - v_ * height_;
            corners[1] = position_ + u_ * width_ - v_ * height_;
            corners[2] = position_ - u_ * width_ + v_ * height_;
            corners[3] = position_ + u_ * width_ + v_ * height_;
            break;
    }

    AABB box(corners[0], corners[0]);
    for (int i = 1; i < 4; ++i) {
        box = AABB(Vec3::min(box.min, corners[i]), Vec3::max(box.max, corners[i]));
    }
    return box;
}

OrientationCone AreaLight::orientationCone() const {
    // Orientation cone: emission is restricted to spread half-angle around normal.
    return OrientationCone::fromAxisAngle(normal_, spread_);
}

// pkg89-GPU / GAP 1 — device upload description mirroring sampleLi() radiometry.
bool AreaLight::fillDeviceParams(DeviceLightParams& out) const {
    out.kind      = DeviceLightParams::Area;
    out.position  = position_;
    out.axis      = normal_;          // emission normal
    out.u         = u_;
    out.v         = v_;
    out.width     = width_;
    out.height    = height_;
    out.areaShape = static_cast<int>(shape_);  // Rectangle=0, Disk=1, Ellipse=2
    out.spread    = spread_;
    emission_.deviceReference(out.emissionRGB, out.exactIlluminant);
    // staticScale = intensity·(1/area)·(1/π); normalizeFactor_ == 1/area.
    // The device recomputes area from shape+width+height for the 1/area pdf.
    constexpr float kM1PiF = 0.31830988618f;
    out.staticScale = intensity_ * normalizeFactor_ * kM1PiF;
    return true;
}

// Helper: sample a point on the shape (uniform area sampling).
Vec3 AreaLight::sampleSurface(std::mt19937& gen) const {
    std::uniform_real_distribution<float> dist(0.0f, 1.0f);
    float u1 = dist(gen);
    float u2 = dist(gen);

    switch (shape_) {
        case Shape::Rectangle: {
            float su = (u1 - 0.5f) * width_;
            float sv = (u2 - 0.5f) * height_;
            return position_ + u_ * su + v_ * sv;
        }
        case Shape::Disk: {
            // Uniform disk sampling.
            float r = std::sqrt(u1) * width_;
            float phi = 2.0f * static_cast<float>(M_PI) * u2;
            return position_ + u_ * (r * std::cos(phi)) + v_ * (r * std::sin(phi));
        }
        case Shape::Ellipse: {
            // Uniform ellipse sampling.
            float r = std::sqrt(u1);
            float phi = 2.0f * static_cast<float>(M_PI) * u2;
            return position_ + u_ * (r * width_ * std::cos(phi)) + v_ * (r * height_ * std::sin(phi));
        }
    }
    return position_;
}

// Helper: check if angle from normal is within spread cone.
bool AreaLight::withinSpread(const Vec3& direction) const {
    float cosTheta = direction.dot(normal_);
    float angle = std::acos(std::clamp(cosTheta, -1.0f, 1.0f));
    return angle <= spread_;
}

} // namespace astroray
