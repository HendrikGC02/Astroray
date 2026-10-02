#pragma once
// ============================================================================
// #991 — Mix Shader whose Fac is a boolean Light Path output (Is Camera Ray,
// Is Shadow Ray, ...). Cycles mixes closure weights (1-f)A + fB with f in {0,1}
// (kernel/svm/closure.h svm_node_mix_closure + svm/light_path.h, Apache-2.0),
// so every ray sees exactly one child. The selection depends on the ray, not
// the hit, so it is made per context:
//   * surface hits: the integrator calls lightPathSelect(rec.lightPath) after
//     the hit (resolveLightPathMaterial, raytracer.h; GPU intersect stage);
//   * shadow rays: shadowAlpha() selects with the shadow context;
//   * emission evaluation (NEE light samples, light list, Triangle::emissive):
//     every boolean output is 0 there, so child A answers (all other virtuals
//     forward to A for the same reason).
// GPU: scene_upload uploads A at this material's id plus a GLightPathSwitch
// side-table entry (astroray/light_path.h).
// ============================================================================

#include "raytracer.h"

namespace astroray {

class LightPathMixMaterial : public Material {
    std::shared_ptr<Material> a_, b_;
    unsigned char output_;

public:
    LightPathMixMaterial(std::shared_ptr<Material> a, std::shared_ptr<Material> b,
                         unsigned char output)
        : a_(std::move(a)), b_(std::move(b)), output_(output) {}

    const std::shared_ptr<Material>& childA() const { return a_; }
    const std::shared_ptr<Material>& childB() const { return b_; }
    unsigned char output() const { return output_; }
    const std::shared_ptr<Material>& select(const lightpath::PathContext& c) const {
        return lightpath::mix_selects_b(output_, c) ? b_ : a_;
    }

    std::shared_ptr<Material> lightPathSelect(const lightpath::PathContext& c) const override {
        return select(c);
    }
    float shadowAlpha(const HitRecord& rec) const override {
        return select(lightpath::shadow_context(rec.lightPath.depth))->shadowAlpha(rec);
    }

    // ---- forwarded to A (the emission-context child) ------------------------
    BSDFSample sample(const HitRecord& r, const Vec3& wo, std::mt19937& g) const override { return a_->sample(r, wo, g); }
    Vec3 eval(const HitRecord& r, const Vec3& wo, const Vec3& wi) const override { return a_->eval(r, wo, wi); }
    float pdf(const HitRecord& r, const Vec3& wo, const Vec3& wi) const override { return a_->pdf(r, wo, wi); }
    Vec3 emitted(const HitRecord& r) const override { return a_->emitted(r); }
    Vec3 getEmission() const override { return a_->getEmission(); }
    bool isEmissive() const override { return a_->isEmissive(); }
    bool isTransmissive() const override { return a_->isTransmissive(); }
    bool isGlossy() const override { return a_->isGlossy(); }
    Vec3 getAlbedo() const override { return a_->getAlbedo(); }
    std::string getGPUTypeName() const override { return a_->getGPUTypeName(); }
    std::shared_ptr<Material> normalMapInner() const override { return a_->normalMapInner(); }
    std::shared_ptr<Texture> normalMapTexture() const override { return a_->normalMapTexture(); }
    float normalMapStrength() const override { return a_->normalMapStrength(); }
    std::shared_ptr<Texture> bumpMapTexture() const override { return a_->bumpMapTexture(); }
    float bumpMapStrength() const override { return a_->bumpMapStrength(); }
    float bumpMapDistance() const override { return a_->bumpMapDistance(); }
    HairGPUParams hairGPUParams() const override { return a_->hairGPUParams(); }
    std::shared_ptr<Texture> scalarProgram(int slot) const override { return a_->scalarProgram(slot); }
    MaterialClosureGraph closureGraph() const override { return a_->closureGraph(); }
    MaterialBackendCapabilities backendCapabilities() const override { return a_->backendCapabilities(); }
    float getRoughness() const override { return a_->getRoughness(); }
    float getMetallic() const override { return a_->getMetallic(); }
    float getIOR() const override { return a_->getIOR(); }
    float iorAt(float l) const override { return a_->iorAt(l); }
    bool isDispersive() const override { return a_->isDispersive(); }
    Vec3 getSellmeierB() const override { return a_->getSellmeierB(); }
    Vec3 getSellmeierC() const override { return a_->getSellmeierC(); }
    Vec3 getCauchyAB() const override { return a_->getCauchyAB(); }
    float getTransmission() const override { return a_->getTransmission(); }
    float getClearcoat() const override { return a_->getClearcoat(); }
    float getClearcoatGloss() const override { return a_->getClearcoatGloss(); }
    float getSpecular() const override { return a_->getSpecular(); }
    float getSpecularTint() const override { return a_->getSpecularTint(); }
    float getSheen() const override { return a_->getSheen(); }
    float getSheenTint() const override { return a_->getSheenTint(); }
    float getSubsurface() const override { return a_->getSubsurface(); }
    float getAnisotropic() const override { return a_->getAnisotropic(); }
    float getAnisotropicRotation() const override { return a_->getAnisotropicRotation(); }
    SampledSpectrum evalSpectral(const HitRecord& r, const Vec3& wo, const Vec3& wi,
                                 const SampledWavelengths& l) const override {
        return a_->evalSpectral(r, wo, wi, l);
    }
    SampledSpectrum emittedSpectral(const HitRecord& r, const SampledWavelengths& l) const override {
        return a_->emittedSpectral(r, l);
    }
    BSDFSampleSpectral sampleSpectral(const HitRecord& r, const Vec3& wo, std::mt19937& g,
                                      SampledWavelengths& l) const override {
        return a_->sampleSpectral(r, wo, g, l);
    }
};

}  // namespace astroray
