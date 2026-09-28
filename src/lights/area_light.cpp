// NOTE: raytracer.h must come BEFORE area_light.h (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/area_light.h"
#include "astroray/spectrum.h"
#include "astroray/area_spread.h"
#include <cmath>
#include <algorithm>
#include <random>

// Reference: Cycles kernel/light/area.h::area_light_sample (Apache-2.0).

// [pkg294-diag] Phase 0 attribution switch - remove before Phase 1 lands.
// ASTRORAY_PKG294_DIAG: unset/0 = baseline; 1 = "mis_sa" (rectangle MIS
// weights at medium vertices use the solid-angle pdf 1/Omega; draw and
// estimator pdf unchanged); 2 = "draw_sa" (rectangle NEE draws + pdfLi use the
// spherical-rectangle solid-angle map everywhere; the segment anchor stays
// area-uniform as in Cycles area_light_eval<true>).
int pkg294DiagMode() {  // [pkg294-diag] remove after Phase 0
    static const int mode = [] {
        const char* e = std::getenv("ASTRORAY_PKG294_DIAG");
        return e ? std::atoi(e) : 0;
    }();
    return mode;
}
thread_local float g_pkg294NeeRatio = 1.0f;  // [pkg294-diag] remove after Phase 0
thread_local bool g_pkg294Anchor = false;    // [pkg294-diag] remove after Phase 0

namespace {
// [pkg294-diag] Port of Cycles kernel/light/area.h::area_light_rect_sample
// (Apache-2.0), itself Urena, Fajardo & King 2013 "An Area-Preserving
// Parametrization for Spherical Rectangles". Returns the solid-angle pdf
// 1/Omega of the rectangle seen from P; when sampleCoord, lightP (in: centre)
// becomes a point drawn uniformly in solid angle. Remove after Phase 0.
float pkg294RectSample(const Vec3& P, Vec3& lightP, const Vec3& x, float lenU,
                       const Vec3& y, float lenV, float r0, float r1, bool sampleCoord) {
    auto sasin = [](float v) { return std::asin(std::min(1.0f, std::max(-1.0f, v))); };
    Vec3 z = x.cross(y);
    const Vec3 dir = lightP - P;
    float z0 = dir.dot(z);
    if (z0 > 0.0f) { z = -z; z0 = -z0; }
    const float xc = dir.dot(x), yc = dir.dot(y);
    const float x0 = xc - 0.5f * lenU, x1 = xc + 0.5f * lenU;
    const float y0 = yc - 0.5f * lenV, y1 = yc + 0.5f * lenV;
    float nz[4] = {-y0, x1, y1, -x0};
    for (float& n : nz) n /= std::sqrt(n * n + z0 * z0);
    const float g0 = sasin(-nz[0] * nz[1]);
    const float g1 = sasin(-nz[1] * nz[2]);
    const float g2 = sasin(-nz[2] * nz[3]);
    const float g3 = sasin(-nz[3] * nz[0]);
    const float S = -(g0 + g1 + g2 + g3);
    if (sampleCoord) {
        const float b0 = nz[0], b1 = nz[2], b0sq = b0 * b0;
        const float au = r0 * S + g2 + g3;
        const float sau = std::sin(au);
        const float fu = sau != 0.0f ? (std::cos(au) * b0 + b1) / sau : 0.0f;
        float cu = std::copysign(1.0f / std::sqrt(fu * fu + b0sq), fu);
        cu = std::min(1.0f, std::max(-1.0f, cu));
        float xu = -(cu * z0) / std::max(std::sqrt(1.0f - cu * cu), 1e-7f);
        xu = std::min(x1, std::max(x0, xu));
        const float d2 = xu * xu + z0 * z0;
        const float h0 = y0 / std::sqrt(d2 + y0 * y0);
        const float h1 = y1 / std::sqrt(d2 + y1 * y1);
        const float hv = h0 + r1 * (h1 - h0), hv2 = hv * hv;
        const float yv = (hv2 < 1.0f - 1e-6f) ? hv * std::sqrt(d2 / (1.0f - hv2)) : y1;
        lightP = P + x * xu + y * yv + z * z0;
    }
    float mn = 1.0f;
    for (float n : nz) mn = std::min(mn, n * n);
    if (S < 1e-5f || mn > 0.99999f) {
        const float t = dir.length();
        const float den = z0 * lenU * lenV;
        return den != 0.0f ? (-t * t * t) / den : 0.0f;
    }
    return 1.0f / S;
}
}  // namespace

namespace astroray {

// [pkg294-diag] lamp-hit MIS ratio (1/Omega) / pdfLi for a full-spread
// rectangle, else 1. Remove after Phase 0.
float pkg294DiagLampHitRatio(const Light* L, const Vec3& P, const Vec3& dir) {
    const AreaLight* A = dynamic_cast<const AreaLight*>(L);
    return A ? A->pkg294SolidAngleRatio(P, dir) : 1.0f;
}

float AreaLight::pkg294SolidAngleRatio(const Vec3& P, const Vec3& dir) const {
    if (shape_ != Shape::Rectangle || spread_ < 0.4999f * static_cast<float>(M_PI)) return 1.0f;
    const float pa = pdfLi(P, dir);
    if (!(pa > 0.0f)) return 1.0f;
    Vec3 c = position_;
    return pkg294RectSample(P, c, u_, width_, v_, height_, 0.0f, 0.0f, false) / pa;
}

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
    // #878: emission_rgb (ReSTIR target, RGB re-upsample consumers) must not
    // depend on the path's hero wavelengths: a 4-lambda toXYZ estimate
    // re-upsampled at the same lambdas is biased (CPU restir-di sun cast).
    // Non-RGB modes (blackbody/measured): refRGB_ is an sRGB approximation that
    // RGB consumers re-upsample as a D65 illuminant; emission_spec stays exact.
    bool exactRGB = false;
    emission_.deviceReference(refRGB_, exactRGB);
}

void AreaLight::sampleLi(LiSample& sample,
                         const Vec3& shadingPoint,
                         const Vec3& shadingNormal,
                         const SampledWavelengths& lambdas,
                         std::mt19937& gen) const {
    // [pkg294-diag] remove after Phase 0: mode 2 draws the rectangle in solid
    // angle (Cycles area_light_eval<false>); the segment anchor stays uniform.
    const bool diagSA = pkg294DiagMode() == 2 && !g_pkg294Anchor &&
                        shape_ == Shape::Rectangle &&
                        spread_ >= 0.4999f * static_cast<float>(M_PI);
    float diagPdf = 0.0f;
    Vec3 sampledPos;
    if (diagSA) {
        std::uniform_real_distribution<float> U(0.0f, 1.0f);
        const float r0 = U(gen), r1 = U(gen);
        sampledPos = position_;
        diagPdf = pkg294RectSample(shadingPoint, sampledPos, u_, width_, v_, height_,
                                   r0, r1, true);
    } else {
        // Sample a point on the area light surface.
        sampledPos = sampleSurface(gen);
    }
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
    // #852: Cycles soft-box spread attenuation (area_spread.h).
    const float scale = intensity_ * normalizeFactor_ * kM1PiF
                      * areaSpreadAttenuation(cosTheta, spread_);
    emissionSpec *= scale;

    sample.emission_spec = emissionSpec;
    sample.emission_rgb = refRGB_ * scale;  // #878

    // PDF in SOLID-ANGLE measure: pdf_ω = pdf_A · dist²/cosθ_light,
    // with pdf_A = 1/area (uniform area sampling). cosTheta > 0 here (rejected
    // above), so the divide is safe.
    sample.pdf = distSq / (area_ * cosTheta);
    // [pkg294-diag] remove after Phase 0.
    if (diagSA) {
        sample.pdf = diagPdf;
    } else if (pkg294DiagMode() == 1 && shape_ == Shape::Rectangle &&
               spread_ >= 0.4999f * static_cast<float>(M_PI)) {
        Vec3 c = position_;
        g_pkg294NeeRatio = pkg294RectSample(shadingPoint, c, u_, width_, v_, height_,
                                            0.0f, 0.0f, false) / sample.pdf;
    }
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
    // [pkg294-diag] remove after Phase 0: mode 2 pairs the solid-angle draw.
    if (pkg294DiagMode() == 2 && shape_ == Shape::Rectangle &&
        spread_ >= 0.4999f * static_cast<float>(M_PI)) {
        Vec3 c = position_;
        return pkg294RectSample(shadingPoint, c, u_, width_, v_, height_, 0.0f, 0.0f, false);
    }
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
    e *= (intensity_ * normalizeFactor_ * kM1PiF
          * areaSpreadAttenuation(-denom, spread_));   // #852, == sampleLi
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

// #851: Lambertian emitter, power = L*A*pi; on-axis intensity L*A (Cycles:
// strength * M_1_PI_F, scene/light_tree.cpp).
float AreaLight::treeEnergy() const {
    return power() / static_cast<float>(M_PI);
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
    // #851: one-sided planar emitter, so theta_o = 0 (all normals == normal_);
    // theta_e = the emission half-angle spread_ (Blender spread / 2, #852),
    // capped at pi/2 by the front-face test. Cycles scene/light_tree.cpp area
    // branch: theta_o = 0, theta_e = spread / 2 (Apache-2.0). The old cone
    // (spread_, spread_) was a full sphere at the default spread, so the tree
    // sampled back-facing area lights.
    return OrientationCone{normal_, 0.0f,
                           std::min(spread_, static_cast<float>(M_PI) * 0.5f)};
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
    // pkg218: baked device SPD for non-RGB emission modes (see point_light.cpp).
    if (!out.exactIlluminant) out.emissionProfileSamples = emission_.bakeDeviceProfile();
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

// #925: one-sided emitter => only the half-space in front of its plane is lit
// (Cycles volume_valid_direct_ray_segment for area lights, Apache-2.0).
bool AreaLight::clipLitSegment(const Vec3& o, const Vec3& d, float& t0, float& t1) const {
    const float s0 = (o - position_).dot(normal_);
    const float dn = d.dot(normal_);
    if (std::abs(dn) < 1e-12f) return s0 > 0.0f;
    const float tp = -s0 / dn;
    if (dn > 0.0f) t0 = std::max(t0, tp);
    else t1 = std::min(t1, tp);
    return t0 < t1;
}

} // namespace astroray
