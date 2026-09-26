// NOTE: raytracer.h must come BEFORE light headers (Vec3/AABB/EmissionSpectrum dependency).
#include "raytracer.h"
#include "astroray/lights/point_light.h"
#include "astroray/spectrum.h"
#include "astroray/lamp_sampling.h"  // #840 Cycles point_light_sample port
#include "raytracer.h"  // for Vec3, IESProfile
#include <cmath>
#include <random>
#include <limits>

// Reference: Cycles kernel/light/point.h::point_light_sample (Apache-2.0).

namespace astroray {

PointLight::PointLight(const Vec3& position,
                        const EmissionSpectrum& emission,
                        float intensity,
                        float radius,
                        const IESProfile* ies)
    : position_(position)
    , emission_(emission)
    , intensity_(intensity)
    , radius_(radius)
    , ies_(ies)
{
    // Compute normalize factor using geometric normalization (Cycles parity).
    // For point lights, pass area=1.0 (normalize factor is just 1/pi).
    normalizeFactor_ = Light::computeNormalizeFactor(1.0f, true);
    // #878: emission_rgb (ReSTIR target, RGB re-upsample consumers) must not
    // depend on the path's hero wavelengths: a 4-lambda toXYZ estimate
    // re-upsampled at the same lambdas is biased (CPU restir-di sun cast).
    // Non-RGB modes (blackbody/measured): refRGB_ is an sRGB approximation that
    // RGB consumers re-upsample as a D65 illuminant; emission_spec stays exact.
    bool exactRGB = false;
    emission_.deviceReference(refRGB_, exactRGB);
    // pkg276: default IES frame (no light object known): local -Z = (0,-1,0),
    // the axis this light used before pkg276.
    iesFz_ = Vec3(0, 1, 0);
    buildOrthonormalBasis(iesFz_, iesFx_, iesFy_);
}

void PointLight::sampleLi(LiSample& sample,
                          const Vec3& shadingPoint,
                          const Vec3& shadingNormal,
                          const SampledWavelengths& lambdas,
                          std::mt19937& gen) const {
    // #840: Cycles kernel/light/point.h point_light_sample via lamp_sampling.h.
    // radius 0: the centre, pdf 1, emission I/d^2 (unchanged). radius > 0: a
    // point on the soft-falloff disk (Blender default) or the visible sphere cap,
    // lamp radiance I/(pi r^2) with a solid-angle pdf. The old uniform-surface
    // point with an area pdf 1/(4 pi r^2) against point-intensity emission scaled
    // the lamp by 4 pi r^2 (0.126x at r = 0.1).
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
    sample.normal = -lightDir;  // normal points outward from light
    sample.distance = distance;

    // 1/d^2 (radius 0) or 1/(pi r^2) (lamp radiance factor, radius > 0).
    float falloff = ls.emit;

    // IES profile modulation (if present).
    float iesModulation = 1.0f;
    if (ies_ != nullptr) {
        // pkg276: Cycles light-local lookup (kernel/svm/ies.h, util/ies.h).
        iesModulation = ies_->sampleFrame(iesFx_, iesFy_, iesFz_, lightDir);
    }

    // Evaluate spectral emission.
    // pkg122 (Defect 2): an isotropic point light of power P has radiant
    // intensity I = P/(4π) (P watts over 4π sr), giving irradiance E = I/d².
    // The prior factor normalizeFactor_(=1)·kM1PiF(=1/π) = 1/π was 4× too large
    // (the pkg89 audit's 3.59× ≈ 4×). Use I = intensity·(1/(4π)).
    // Reference: Cycles scene/light.cpp point path (area = 4π·radius²,
    //   invarea = 1/area, eval_fac = invarea·M_1_PI_F) → intensity P/(4π);
    //   kernel/light/point.h::point_light_sample (Apache-2.0).
    constexpr float kInvFourPiF = 0.07957747155f;  // 1/(4π)
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    const float scale = intensity_ * kInvFourPiF * falloff * iesModulation;
    emissionSpec *= scale;

    sample.emission_spec = emissionSpec;
    sample.emission_rgb = refRGB_ * scale;  // #878

    // PDF: 1 for radius 0 (delta); solid-angle pdf for radius > 0 (#840).
    sample.pdf = ls.pdf;
    // Batch P: point/spot lamps are NEE-only here (no BSDF-ray intersection; GPU
    // gpu_dedicated_intersect / reconstruct_pdf also skip them), so NEE must not be
    // MIS-weighted against a BSDF strategy that can never reach them. For radius 0
    // this is exactly Cycles (SHADER_USE_MIS only when radius > 0, scene/light.cpp;
    // BSDF pdf zeroed for non-MIS lights, kernel/integrator/surface_shader.h).
    // Measured before: NEE weight 1/(1+(cos/pi)^2) -> 0.91x (1 light) .. 0.40x (4).
    sample.isDelta = true;
}

float PointLight::pdfLi(const Vec3& shadingPoint, const Vec3& direction) const {
    // #840: NEE-only lamp (never hit by BSDF rays), so it adds nothing to the
    // BSDF-hit MIS pdf of OTHER emitters (LightList::pdfValue). The old radius>0
    // value was a direction-independent AREA pdf 1/(4 pi r^2), which diluted the
    // BSDF weight of every emitter hit in scenes with a soft point lamp. Mirrors
    // the GPU gpu_dedicated_reconstruct_pdf (point/spot contribute nothing).
    (void)shadingPoint; (void)direction;
    return 0.0f;
}

float PointLight::power() const {
    // Total emitted power: integrate emission over all directions.
    // For an isotropic point light, power ~ intensity × (4π steradians).
    // We approximate by sampling emission at D65-like wavelengths and converting to luminance.
    SampledWavelengths lambdas = SampledWavelengths::sampleUniform(0.5f);
    SampledSpectrum emissionSpec = emission_.eval(lambdas);
    XYZ xyz = emissionSpec.toXYZ(lambdas);
    float luminance = xyz.Y;  // photopic luminance
    return luminance * intensity_ * normalizeFactor_ * 4.0f * static_cast<float>(M_PI);
}

// #851: isotropic, intensity = power / 4pi (Cycles: strength * 0.25 * M_1_PI_F).
float PointLight::treeEnergy() const {
    return power() / (4.0f * static_cast<float>(M_PI));
}

AABB PointLight::bounds() const {
    // Point light has negligible spatial extent (or small sphere for soft shadows).
    Vec3 r(radius_, radius_, radius_);
    return AABB(position_ - r, position_ + r);
}

OrientationCone PointLight::orientationCone() const {
    // Isotropic emission (or IES-modulated isotropic).
    // pkg89 Q12: IES on PointLight widens to full-sphere cone.
    return OrientationCone::fullSphere();
}

// pkg89-GPU / GAP 1 — device upload description mirroring sampleLi() radiometry.
bool PointLight::fillDeviceParams(DeviceLightParams& out) const {
    out.kind     = DeviceLightParams::Point;
    out.position = position_;
    out.radius   = radius_;
    emission_.deviceReference(out.emissionRGB, out.exactIlluminant);
    // pkg218: non-RGB modes (blackbody/measured_spd/composite) also get a
    // baked device SPD so the GPU can render the exact emission spectrum
    // instead of the RGBIlluminant approximation (see gpu_nee.cuh
    // gpu_nee_resolve). RGB mode leaves this empty — its deviceReference path
    // is already exact.
    if (!out.exactIlluminant) out.emissionProfileSamples = emission_.bakeDeviceProfile();
    // pkg122 (Defect 2): staticScale = intensity·(1/(4π)) = radiant intensity
    // I = P/(4π). Matches sampleLi: emissionSpec *= intensity_ * kInvFourPiF * falloff.
    constexpr float kInvFourPiF = 0.07957747155f;  // 1/(4π)
    out.staticScale = intensity_ * kInvFourPiF;
    // #840: point/spot reuse areaShape as the radius>0 mode: 0 soft-falloff disk
    // (Blender default), 1 sphere (use_soft_falloff off).
    out.areaShape = softFalloff_ ? 0 : 1;
    // pkg276: the IES table (Cycles packed layout) + light frame for the GPU side table.
    if (ies_ != nullptr) {
        out.iesPacked = ies_->packed();
        out.iesFrame = {iesFx_.x, iesFx_.y, iesFx_.z, iesFy_.x, iesFy_.y, iesFy_.z,
                        iesFz_.x, iesFz_.y, iesFz_.z};
    }
    return true;
}

} // namespace astroray
