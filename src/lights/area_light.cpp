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

    // pkg122 (Defect 1): emission is PLAIN RADIANCE and the pdf is returned in
    // SOLID-ANGLE measure — matching Cycles area_light_sample and the geometry-
    // emitter path (light_sampler.cpp:64-70). The previous code folded the
    // geometric factor cosθ/dist² into the emission while returning an area-
    // measure pdf 1/area; the L/pdf divide was numerically correct but the pdf
    // being area-measure made the integrator's MIS weight (which combines
    // ls.pdf with a SOLID-ANGLE bsdfPdf) size-dependent — the 0.13×/1.40× bias
    // the pkg89 audit measured. See pkg122 research note.
    // Reference: Cycles kernel/light/area.h::area_light_sample
    //   (eval_fac = M_1_PI_F * invarea = plain radiance;
    //    ls->pdf *= light_pdf_area_to_solid_angle(Ng, -D, t)) (Apache-2.0).
    float distSq = distance * distance;

    // Evaluate spectral emission — plain Lambertian radiance L_e = P/(π·A).
    constexpr float kM1PiF = 0.31830988618f;  // M_1_PI_F = 1/π
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    emissionSpec *= (intensity_ * normalizeFactor_ * kM1PiF);

    sample.emission_spec = emissionSpec;

    // Convert to RGB.
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    sample.emission_rgb = Vec3(
        3.2404542f * xyz.X - 1.5371385f * xyz.Y - 0.4985314f * xyz.Z,
        -0.9692660f * xyz.X + 1.8760108f * xyz.Y + 0.0415560f * xyz.Z,
        0.0556434f * xyz.X - 0.2040259f * xyz.Y + 1.0572252f * xyz.Z
    );

    // PDF in SOLID-ANGLE measure: pdf_ω = pdf_A · dist²/cosθ_light,
    // with pdf_A = 1/area (uniform area sampling). cosTheta > 0 here (rejected
    // above), so the divide is safe.
    sample.pdf = distSq / (area_ * cosTheta);
}

namespace {
// pkg181: is the in-plane offset (u,v) from the light center inside the shape?
// Mirrors Cycles area_light_intersect in-bounds test (kernel/light/area.h,
// Apache-2.0). Frame conventions match sampleSurface(): rectangle spans
// [-width/2,width/2]×[-height/2,height/2]; disk radius = width; ellipse
// semi-axes (width, height).
inline bool areaInBounds(AreaLight::Shape shape, float u, float v,
                         float width, float height) {
    switch (shape) {
        case AreaLight::Shape::Rectangle:
            return std::abs(u) <= 0.5f * width && std::abs(v) <= 0.5f * height;
        case AreaLight::Shape::Disk:
            return (u * u + v * v) <= width * width;   // width == radius
        case AreaLight::Shape::Ellipse: {
            float su = u / width, sv = v / height;
            return (su * su + sv * sv) <= 1.0f;
        }
    }
    return false;
}
}  // namespace

float AreaLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    // pkg181: solid-angle-measure pdf, direction-tested — the measure the NEE
    // leg samples in (sampleLi returns pdf = d²/(area·cosθ)), so the pkg120
    // two-sided-MIS BSDF-hit leg reconstructs a consistent weight. Returns 0
    // when `direction` (shading point → light) misses the surface, hits the
    // back face, or falls outside the spread cone. The prior `1/area` was
    // area-measure AND direction-independent (contaminated the MIS sum for
    // every direction). Reference: Cycles light_pdf_area_to_solid_angle
    // (kernel/light/area.h, Apache-2.0).
    Vec3 d = direction.normalized();
    float denom = d.dot(normal_);
    if (denom >= 0.0f) return 0.0f;                    // parallel or back face
    float t = (position_ - shadingPoint).dot(normal_) / denom;
    if (t <= 0.0f) return 0.0f;
    Vec3 P = shadingPoint + d * t;
    Vec3 off = P - position_;
    float uu = off.dot(u_), vv = off.dot(v_);
    if (!areaInBounds(shape_, uu, vv, width_, height_)) return 0.0f;
    if (!withinSpread(-d)) return 0.0f;                // -d = light→receiver dir
    float cosLight = -denom;                           // cosθ at the light (>0)
    return (t * t) / (area_ * cosLight);
}

bool AreaLight::intersect(const Vec3& rayOrigin, const Vec3& rayDir,
                          float tMin, float tMax,
                          const SampledWavelengths& lambdas,
                          Intersection& out) const {
    // pkg181: ray-plane intersection + in-bounds test (Cycles
    // area_light_intersect / area_light_eval_from_intersection parity,
    // kernel/light/area.h, Apache-2.0). One-sided: the ray must travel toward
    // the front face (dot(D, Ng) < 0), matching sampleLi's cosθ>0 gate.
    Vec3 D = rayDir.normalized();
    float denom = D.dot(normal_);
    if (denom >= 0.0f) return false;                   // back face / parallel
    float t = (position_ - rayOrigin).dot(normal_) / denom;
    if (t <= tMin || t > tMax) return false;
    Vec3 P = rayOrigin + D * t;
    Vec3 off = P - position_;
    float uu = off.dot(u_), vv = off.dot(v_);
    if (!areaInBounds(shape_, uu, vv, width_, height_)) return false;
    Vec3 dirToReceiver = -D;                            // emitted direction
    if (!withinSpread(dirToReceiver)) return false;    // out of spread cone → dark

    out.t = t;
    out.position = P;
    out.normal = normal_;
    // Plain Lambertian radiance L_e = P/(π·A) — identical to sampleLi's
    // emission_spec (the geometry is carried by the pdf / throughput, not here).
    constexpr float kM1PiF = 0.31830988618f;  // 1/π
    SampledSpectrum e = emission_.eval(lambdas);
    e *= (intensity_ * normalizeFactor_ * kM1PiF);
    out.emission = e;
    return true;
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
    // staticScale = intensity·(1/area)·(1/π) = plain Lambertian radiance L_e =
    // P/(π·A); normalizeFactor_ == 1/area. pkg122: the device carries L_e directly
    // and recomputes area from shape+width+height for the SOLID-ANGLE pdf
    // (dist²/(area·cosθ)); the old cosθ/dist² fold + area-measure pdf is gone.
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
