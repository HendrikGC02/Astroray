// NOTE: raytracer.h must come BEFORE light headers (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/spot_light.h"
#include "astroray/spectrum.h"
#include "astroray/lamp_sampling.h"  // #840 Cycles point_light_sample port
#include "raytracer.h"  // for Vec3, IESProfile
#include <cmath>
#include <algorithm>
#include <random>
#include <limits>

// Reference: Cycles kernel/light/spot.h::spot_light_sample (Apache-2.0).

namespace astroray {

SpotLight::SpotLight(const Vec3& position,
                      const Vec3& axis,
                      float innerAngle,
                      float outerAngle,
                      const EmissionSpectrum& emission,
                      float intensity,
                      float radius,
                      const IESProfile* ies)
    : position_(position)
    , axis_(axis.normalized())
    , innerAngle_(innerAngle)
    , outerAngle_(outerAngle)
    , emission_(emission)
    , intensity_(intensity)
    , radius_(radius)
    , ies_(ies)
{
    // Compute normalize factor using geometric normalization (Cycles parity).
    // For point/spot lights, pass area=1.0 (normalize factor is just 1/pi).
    normalizeFactor_ = Light::computeNormalizeFactor(1.0f, true);
    // #878: emission_rgb (ReSTIR target, RGB re-upsample consumers) must not
    // depend on the path's hero wavelengths: a 4-lambda toXYZ estimate
    // re-upsampled at the same lambdas is biased (CPU restir-di sun cast).
    // Non-RGB modes (blackbody/measured): refRGB_ is an sRGB approximation that
    // RGB consumers re-upsample as a D65 illuminant; emission_spec stays exact.
    bool exactRGB = false;
    emission_.deviceReference(refRGB_, exactRGB);
    // pkg276: default IES frame (no light object known): local -Z = axis.
    iesFz_ = -axis_;
    buildOrthonormalBasis(iesFz_, iesFx_, iesFy_);
}

void SpotLight::sampleLi(LiSample& sample,
                         const Vec3& shadingPoint,
                         const Vec3& shadingNormal,
                         const SampledWavelengths& lambdas,
                         std::mt19937& gen) const {
    // #840: Cycles kernel/light/spot.h spot_light_sample via lamp_sampling.h
    // (see point_light.cpp): radius 0 unchanged; radius > 0 samples the
    // soft-falloff disk or the sphere cap with a solid-angle pdf and lamp
    // radiance I/(pi r^2); the cone attenuation is evaluated per sampled point.
    float u1 = 0.0f, u2 = 0.0f;
    if (radius_ > 0.0f) {
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        u1 = dist(gen);
        u2 = dist(gen);
    }
    const float c[3] = {position_.x, position_.y, position_.z};
    const float p[3] = {shadingPoint.x, shadingPoint.y, shadingPoint.z};
    const lamp::Sample ls = lamp::sample(c, radius_, !softFalloff_, p, u1, u2);
    if (!ls.valid) {
        sample.emission_spec = SampledSpectrum(0.0f);
        sample.emission_rgb = Vec3(0);
        sample.pdf = 0.0f;
        sample.isDelta = true;
        return;
    }
    Vec3 sampledPos(ls.q[0], ls.q[1], ls.q[2]);
    Vec3 lightToShading = shadingPoint - sampledPos;
    float distance = lightToShading.length();
    Vec3 lightDir = lightToShading / distance;

    sample.position = sampledPos;
    sample.normal = -lightDir;
    sample.distance = distance;

    // Cone attenuation; Cycles skips it inside a sphere lamp (ls.outside == 0).
    float cosTheta = lightDir.dot(axis_);
    float angleFalloffFactor = 1.0f;
    if (ls.outside) {
        float angleFromAxis = std::acos(std::clamp(cosTheta, -1.0f, 1.0f));
        if (angleFromAxis > outerAngle_) {
            // Outside cone: zero emission.
            sample.emission_spec = SampledSpectrum(0.0f);
            sample.emission_rgb = Vec3(0);
            sample.pdf = 0.0f;
            sample.isDelta = true;
            return;
        }
        // Angle falloff (smooth transition from inner to outer cone).
        angleFalloffFactor = angleFalloff(cosTheta);
    }

    // 1/d^2 (radius 0) or 1/(pi r^2) (lamp radiance factor, radius > 0).
    float falloff = ls.emit;

    // IES profile modulation (if present).
    float iesModulation = 1.0f;
    if (ies_ != nullptr) {
        // pkg276: Cycles light-local lookup (kernel/svm/ies.h, util/ies.h).
        iesModulation = ies_->sampleFrame(iesFx_, iesFy_, iesFz_, lightDir);
    }

    // Evaluate spectral emission.
    // pkg122: a Blender spot light is a point light of power P masked by the
    // cone, so it carries the same radiant intensity I = P/(4π) as the point
    // light (Cycles kernel/light/spot.h inherits spot.eval_fac from the point
    // path). The prior 1/π was 4× too large. Apache-2.0.
    constexpr float kInvFourPiF = 0.07957747155f;  // 1/(4π)
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    const float scale = intensity_ * kInvFourPiF * falloff * angleFalloffFactor * iesModulation;
    emissionSpec *= scale;

    sample.emission_spec = emissionSpec;
    sample.emission_rgb = refRGB_ * scale;  // #878

    // pkg122: a radius-0 spot is a DELTA light (single direction to the source),
    // so pdf = 1 like the point light — the 1/d² falloff and cone attenuation are
    // already baked into emission. The prior 1/coneSolidAngle made the L/pdf
    // divide multiply brightness by the cone solid angle (cone-angle-dependent
    // over-bright). For radius>0 the sphere emitter uses uniform-surface pdf
    // 1/(4π·r²), matching the point sphere light (Cycles spot inherits point).
    sample.pdf = ls.pdf;   // 1 for radius 0 (delta); solid-angle pdf for radius > 0 (#840)
    // Batch P: point/spot lamps are NEE-only here (no BSDF-ray intersection; GPU
    // gpu_dedicated_intersect / reconstruct_pdf also skip them), so NEE must not be
    // MIS-weighted against a BSDF strategy that can never reach them. For radius 0
    // this is exactly Cycles (SHADER_USE_MIS only when radius > 0, scene/light.cpp;
    // BSDF pdf zeroed for non-MIS lights, kernel/integrator/surface_shader.h).
    // Measured before: NEE weight 1/(1+(cos/pi)^2) -> 0.91x (1 light) .. 0.40x (4).
    sample.isDelta = true;
}

float SpotLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    // #840: NEE-only lamp -- contributes nothing to other emitters' BSDF-hit MIS
    // pdf (see PointLight::pdfLi; mirrors gpu_dedicated_reconstruct_pdf).
    (void)shadingPoint; (void)direction;
    return 0.0f;
}

float SpotLight::power() const {
    // Power estimate: integrate emission over the cone solid angle.
    SampledWavelengths lambdas = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    float luminance = xyz.Y;
    float coneSolidAngle = 2.0f * static_cast<float>(M_PI) * (1.0f - std::cos(outerAngle_));
    return luminance * intensity_ * normalizeFactor_ * coneSolidAngle;
}

// #851: on-axis intensity = power / cone solid angle, the point-light
// intensity Cycles uses for spots (strength * 0.25 * M_1_PI_F).
float SpotLight::treeEnergy() const {
    float coneSolidAngle = 2.0f * static_cast<float>(M_PI) * (1.0f - std::cos(outerAngle_));
    return coneSolidAngle > 0.0f ? power() / coneSolidAngle : power();
}

AABB SpotLight::bounds() const {
    Vec3 r(radius_, radius_, radius_);
    return AABB(position_ - r, position_ + r);
}

OrientationCone SpotLight::orientationCone() const {
    return OrientationCone::fromAxisAngle(axis_, outerAngle_);
}

// Helper: compute falloff for angle θ from axis.
// Smooth transition from inner (full intensity) to outer (zero).
// Reference: Cycles intern/cycles/kernel/light/spot.h::spot_light_attenuation
// and intern/cycles/util/math_base.h::smoothstepf (Apache-2.0).
float SpotLight::angleFalloff(float cosTheta) const {
    float cosOuter = std::cos(outerAngle_);
    float cosInner = std::cos(innerAngle_);

    if (cosTheta >= cosInner) {
        return 1.0f;  // inside inner cone
    }
    if (cosTheta <= cosOuter) {
        return 0.0f;  // outside outer cone
    }

    // Cycles cubic Hermite smoothstep: 3t² - 2t³ (zero derivative at endpoints).
    float t = (cosTheta - cosOuter) / (cosInner - cosOuter);
    return t * t * (3.0f - 2.0f * t);
}

// pkg89-GPU / GAP 1 — device upload description mirroring sampleLi() radiometry.
bool SpotLight::fillDeviceParams(DeviceLightParams& out) const {
    out.kind     = DeviceLightParams::Spot;
    out.position = position_;
    out.axis     = axis_;
    out.radius   = radius_;
    out.cosInner = std::cos(innerAngle_);
    out.cosOuter = std::cos(outerAngle_);
    emission_.deviceReference(out.emissionRGB, out.exactIlluminant);
    // pkg218: baked device SPD for non-RGB emission modes (see point_light.cpp).
    if (!out.exactIlluminant) out.emissionProfileSamples = emission_.bakeDeviceProfile();
    // pkg122: staticScale = intensity·(1/(4π)) = I = P/(4π), matching sampleLi.
    constexpr float kInvFourPiF = 0.07957747155f;  // 1/(4π)
    out.staticScale = intensity_ * kInvFourPiF;
    // #840: radius>0 mode in areaShape (0 soft-falloff disk, 1 sphere).
    out.areaShape = softFalloff_ ? 0 : 1;
    // pkg276: the IES table (Cycles packed layout) + light frame for the GPU side table.
    if (ies_ != nullptr) {
        out.iesPacked = ies_->packed();
        out.iesFrame = {iesFx_.x, iesFx_.y, iesFx_.z, iesFy_.x, iesFy_.y, iesFy_.z,
                        iesFz_.x, iesFz_.y, iesFz_.z};
    }
    return true;
}

// #925: clip a ray segment to the spot cone (Cycles
// volume_valid_direct_ray_segment / spot_light_valid_ray_segment, Apache-2.0).
// Conservative: outer angle + 1e-3 and the apex pulled back by r/sin(θ) so the
// cone contains the lamp sphere (a radius>0 spot emits from inside it).
bool SpotLight::clipLitSegment(const Vec3& o, const Vec3& d, float& t0, float& t1) const {
    const double th = double(outerAngle_) + 1e-3;
    if (th >= 1.55) return true;
    const double sinT = std::sin(th), cosT = std::cos(th), c2 = cosT * cosT;
    const double ax = axis_.x, ay = axis_.y, az = axis_.z;
    const double pull = double(radius_) / sinT;
    const double cox = double(o.x) - (double(position_.x) - ax * pull);
    const double coy = double(o.y) - (double(position_.y) - ay * pull);
    const double coz = double(o.z) - (double(position_.z) - az * pull);
    const double dx = d.x, dy = d.y, dz = d.z;
    const double dv = dx * ax + dy * ay + dz * az;
    const double cv = cox * ax + coy * ay + coz * az;
    double lo = t0, hi = t1;
    // Positive nappe: axial coordinate >= 0.
    if (std::abs(dv) < 1e-12) {
        if (cv < 0.0) return false;
    } else if (dv > 0.0) {
        lo = std::max(lo, -cv / dv);
    } else {
        hi = std::min(hi, -cv / dv);
    }
    if (!(lo <= hi)) return false;
    // Inside the double cone: f(t) = (cv + t dv)^2 - cos^2 |co + t d|^2 >= 0.
    const double qa = dv * dv - c2;
    const double qb = 2.0 * (cv * dv - c2 * (cox * dx + coy * dy + coz * dz));
    const double qc = cv * cv - c2 * (cox * cox + coy * coy + coz * coz);
    const double inf = std::numeric_limits<double>::infinity();
    double pieces[2][2];
    int n = 0;
    if (std::abs(qa) < 1e-12) {
        if (std::abs(qb) < 1e-18) { if (qc < 0.0) return false; pieces[n][0] = -inf; pieces[n++][1] = inf; }
        else if (qb > 0.0) { pieces[n][0] = -qc / qb; pieces[n++][1] = inf; }
        else { pieces[n][0] = -inf; pieces[n++][1] = -qc / qb; }
    } else {
        const double disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) {
            if (qa < 0.0) return false;
            pieces[n][0] = -inf; pieces[n++][1] = inf;
        } else {
            const double sq = std::sqrt(disc);
            double r1 = (-qb - sq) / (2.0 * qa), r2 = (-qb + sq) / (2.0 * qa);
            if (r1 > r2) std::swap(r1, r2);
            if (qa > 0.0) {
                pieces[n][0] = -inf; pieces[n++][1] = r1;
                pieces[n][0] = r2;   pieces[n++][1] = inf;
            } else {
                pieces[n][0] = r1; pieces[n++][1] = r2;
            }
        }
    }
    // Within the half-space the cone is convex: take the hull of what survives.
    double nlo = inf, nhi = -inf;
    for (int k = 0; k < n; ++k) {
        const double pad = 1e-4 * (1.0 + std::min(std::abs(pieces[k][0]), std::abs(pieces[k][1])));
        const double a = std::max(lo, pieces[k][0] - pad), b = std::min(hi, pieces[k][1] + pad);
        if (a <= b) { nlo = std::min(nlo, a); nhi = std::max(nhi, b); }
    }
    if (!(nlo <= nhi)) return false;
    t0 = float(nlo);
    t1 = float(nhi);
    return true;
}

} // namespace astroray
