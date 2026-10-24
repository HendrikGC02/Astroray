#pragma once
// ============================================================================
// #995 / #955 -- closure composition: Add Shader and Mix Shader as one binary
// closure node with per-hit child weights (wA, wB). Ported semantics, Cycles 5.2
// (Apache-2.0):
//   * kernel/svm/closure.h:1506-1522 svm_node_mix_closure: fac = saturatef(Fac)
//     evaluated at the shading point; the children get in_weight * (1 - fac) and
//     in_weight * fac. Add Shader passes the incoming weight to both children
//     (the closures simply accumulate), so wA = wB = 1.
//   * kernel/integrator/surface_shader.h:436-470: one BSDF closure is picked in
//     proportion to its sample weight (kernel/closure/alloc.h:55-62, |avg(weight)|);
//     :271-315 and :973-1010: the sampled direction is then evaluated on every
//     closure, f = sum w_i f_i, pdf = sum q_i p_i (Veach 1997 one-sample model,
//     balance heuristic). Emission closures are never picked.
//   * kernel/integrator/shade_surface.h:818-869: emission is accumulated and the
//     path continues through the BSDF closures (Material::hasBSDF).
// Here each node picks child c with q_c = w_c [c has a BSDF] / sum, recursively, so
// nested nodes give a product of local probabilities. That equals Cycles' flat pick
// for Mix trees and is an unbiased mixture otherwise (the estimator only needs
// q_c > 0 wherever w_c f_c != 0). A delta child sample cannot be summed with the
// other child's eval (0 at a delta), so it is returned alone: f * w_c, pdf * q_c.
// Shadow opacity: Cycles sums the transparent closure weights, so the opacity is
// 1 - sum w_i (1 - alpha_i), clamped to [0, 1].
// ============================================================================

#include <algorithm>
#include <cmath>
#include <random>
#include "raytracer.h"
#include "advanced_features.h"   // Texture (the per-hit Mix Fac)
#include "light_path_mix.h"

namespace astroray {

class ClosureNodeMaterial : public Material {
protected:
    std::shared_ptr<Material> a_, b_;

public:
    ClosureNodeMaterial(std::shared_ptr<Material> a, std::shared_ptr<Material> b)
        : a_(std::move(a)), b_(std::move(b)) {}

    const std::shared_ptr<Material>& childA() const { return a_; }
    const std::shared_ptr<Material>& childB() const { return b_; }

    // Physical closure weights of the two children at this shading point.
    virtual void weights(const HitRecord& r, const Vec3& wo, float& wA, float& wB) const = 0;

    // Child selection probabilities (see the header comment).
    void probabilities(float wA, float wB, float& qA, float& qB) const {
        const float sA = a_->hasBSDF() ? wA : 0.0f;
        const float sB = b_->hasBSDF() ? wB : 0.0f;
        const float s = sA + sB;
        qA = (s > 0.0f) ? sA / s : 0.0f;
        qB = (s > 0.0f) ? sB / s : 0.0f;
    }

    // ---- BSDF: weighted sum + one-sample MIS -----------------------------------
    Vec3 eval(const HitRecord& r, const Vec3& wo, const Vec3& wi) const override {
        float wA, wB;
        weights(r, wo, wA, wB);
        Vec3 f(0.0f);
        if (wA > 0.0f) f = f + a_->eval(r, wo, wi) * wA;
        if (wB > 0.0f) f = f + b_->eval(r, wo, wi) * wB;
        return f;
    }
    float pdf(const HitRecord& r, const Vec3& wo, const Vec3& wi) const override {
        float wA, wB, qA, qB;
        weights(r, wo, wA, wB);
        probabilities(wA, wB, qA, qB);
        float p = 0.0f;
        if (qA > 0.0f) p += qA * a_->pdf(r, wo, wi);
        if (qB > 0.0f) p += qB * b_->pdf(r, wo, wi);
        return p;
    }
    BSDFSample sample(const HitRecord& r, const Vec3& wo, std::mt19937& g) const override {
        float wA, wB, qA, qB;
        weights(r, wo, wA, wB);
        probabilities(wA, wB, qA, qB);
        const bool pickB = std::uniform_real_distribution<float>(0.0f, 1.0f)(g) < qB;
        if (qA + qB <= 0.0f) return BSDFSample{Vec3(0, 1, 0), Vec3(0), 0.0f, false};
        const Material& c = pickB ? *b_ : *a_;
        const Material& o = pickB ? *a_ : *b_;
        const float wc = pickB ? wB : wA, wo_ = pickB ? wA : wB;
        const float qc = pickB ? qB : qA, qo = pickB ? qA : qB;
        BSDFSample s = c.sample(r, wo, g);
        if (s.pdf <= 0.0f) return s;
        s.f = s.f * wc;
        if (s.isDelta) { s.pdf *= qc; return s; }
        if (wo_ > 0.0f) s.f = s.f + o.eval(r, wo, s.wi) * wo_;
        s.pdf = qc * s.pdf + (qo > 0.0f ? qo * o.pdf(r, wo, s.wi) : 0.0f);
        return s;
    }
    SampledSpectrum evalSpectral(const HitRecord& r, const Vec3& wo, const Vec3& wi,
                                 const SampledWavelengths& l) const override {
        float wA, wB;
        weights(r, wo, wA, wB);
        SampledSpectrum f(0.0f);
        if (wA > 0.0f) f = f + a_->evalSpectral(r, wo, wi, l) * wA;
        if (wB > 0.0f) f = f + b_->evalSpectral(r, wo, wi, l) * wB;
        return f;
    }
    BSDFSampleSpectral sampleSpectral(const HitRecord& r, const Vec3& wo, std::mt19937& g,
                                      SampledWavelengths& l) const override {
        float wA, wB, qA, qB;
        weights(r, wo, wA, wB);
        probabilities(wA, wB, qA, qB);
        const bool pickB = std::uniform_real_distribution<float>(0.0f, 1.0f)(g) < qB;
        if (qA + qB <= 0.0f) {
            BSDFSampleSpectral z;
            z.wi = Vec3(0, 1, 0); z.f_spectral = SampledSpectrum(0.0f); z.pdf = 0.0f; z.isDelta = false;
            return z;
        }
        const Material& c = pickB ? *b_ : *a_;
        const Material& o = pickB ? *a_ : *b_;
        const float wc = pickB ? wB : wA, wo_ = pickB ? wA : wB;
        const float qc = pickB ? qB : qA, qo = pickB ? qA : qB;
        BSDFSampleSpectral s = c.sampleSpectral(r, wo, g, l);
        if (s.pdf <= 0.0f) return s;
        s.f_spectral = s.f_spectral * wc;
        if (s.isDelta) { s.pdf *= qc; return s; }
        if (wo_ > 0.0f) s.f_spectral = s.f_spectral + o.evalSpectral(r, wo, s.wi, l) * wo_;
        s.pdf = qc * s.pdf + (qo > 0.0f ? qo * o.pdf(r, wo, s.wi) : 0.0f);
        return s;
    }

    // ---- emission and shadow opacity: weighted ---------------------------------
    Vec3 emitted(const HitRecord& r) const override {
        float wA, wB;
        weights(r, -r.incomingDirection, wA, wB);
        Vec3 e(0.0f);
        if (wA > 0.0f) e = e + a_->emitted(r) * wA;
        if (wB > 0.0f) e = e + b_->emitted(r) * wB;
        return e;
    }
    SampledSpectrum emittedSpectral(const HitRecord& r, const SampledWavelengths& l) const override {
        float wA, wB;
        weights(r, -r.incomingDirection, wA, wB);
        SampledSpectrum e(0.0f);
        if (wA > 0.0f) e = e + a_->emittedSpectral(r, l) * wA;
        if (wB > 0.0f) e = e + b_->emittedSpectral(r, l) * wB;
        return e;
    }
    float shadowAlpha(const HitRecord& r) const override {
        float wA, wB;
        weights(r, -r.incomingDirection, wA, wB);
        const float transparent = wA * (1.0f - a_->shadowAlpha(r)) + wB * (1.0f - b_->shadowAlpha(r));
        return std::clamp(1.0f - transparent, 0.0f, 1.0f);
    }
    bool hasBSDF() const override { return a_->hasBSDF() || b_->hasBSDF(); }
    bool isTransmissive() const override { return a_->isTransmissive() || b_->isTransmissive(); }
    bool isGlossy() const override { return a_->isGlossy() || b_->isGlossy(); }
    // #1045: a smooth conductor + smooth conductor stays delta-only; anything else has a lobe.
    bool isDeltaOnly() const override { return a_->isDeltaOnly() && b_->isDeltaOnly(); }
    // Forwarded to A (a Light Path switch nested under Add / Mix keeps child A's branch;
    // the addon reports it).
    std::shared_ptr<Material> lightPathSelect(const lightpath::PathContext& c) const override {
        return a_->lightPathSelect(c);
    }

    // ---- GPU upload / parameter queries: child A (scene_upload lowers the node) ----
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
    float getRoughness() const override { return a_->getRoughness(); }
    float getMetallic() const override { return a_->getMetallic(); }
    // Refraction parameters come from the transmissive child (isTransmissive ORs both).
    const Material& refractive() const { return (!a_->isTransmissive() && b_->isTransmissive()) ? *b_ : *a_; }
    float getIOR() const override { return refractive().getIOR(); }
    float iorAt(float l) const override { return refractive().iorAt(l); }
    bool isDispersive() const override { return refractive().isDispersive(); }
    Vec3 getSellmeierB() const override { return refractive().getSellmeierB(); }
    Vec3 getSellmeierC() const override { return refractive().getSellmeierC(); }
    Vec3 getCauchyAB() const override { return refractive().getCauchyAB(); }
    float getTransmission() const override { return refractive().getTransmission(); }
    float getClearcoat() const override { return a_->getClearcoat(); }
    float getClearcoatGloss() const override { return a_->getClearcoatGloss(); }
    float getSpecular() const override { return a_->getSpecular(); }
    float getSpecularTint() const override { return a_->getSpecularTint(); }
    float getSheen() const override { return a_->getSheen(); }
    float getSheenTint() const override { return a_->getSheenTint(); }
    float getSubsurface() const override { return a_->getSubsurface(); }
    float getAnisotropic() const override { return a_->getAnisotropic(); }
    float getAnisotropicRotation() const override { return a_->getAnisotropicRotation(); }
};

// Mix Shader(Fac, A, B): wA = 1 - fac, wB = fac, with fac = saturate(Fac) evaluated per
// hit from `facTex` (op-VM / graph program, scalar in .x) or the constant `fac`.
class MixMaterial : public ClosureNodeMaterial {
    float fac_;
    std::shared_ptr<Texture> facTex_;

    static float saturate(float v) { return std::fmin(std::fmax(v, 0.0f), 1.0f); }  // NaN -> 0

public:
    MixMaterial(std::shared_ptr<Material> a, std::shared_ptr<Material> b, float fac,
                std::shared_ptr<Texture> facTex)
        : ClosureNodeMaterial(std::move(a), std::move(b)), fac_(saturate(fac)),
          facTex_(std::move(facTex)) {}

    float constantFac() const { return fac_; }
    const std::shared_ptr<Texture>& facTexture() const { return facTex_; }
    float facAt(const HitRecord& r, const Vec3& wo) const {
        return facTex_ ? saturate(facTex_->value(r, wo).x) : fac_;
    }
    void weights(const HitRecord& r, const Vec3& wo, float& wA, float& wB) const override {
        const float f = facAt(r, wo);
        wA = 1.0f - f;
        wB = f;
    }
    // Light-list power: the constant Fac, or the Fac texture's mean.
    float meanFac() const { return facTex_ ? saturate(facTex_->average().x) : fac_; }
    Vec3 getEmission() const override {
        const float f = meanFac();
        return a_->getEmission() * (1.0f - f) + b_->getEmission() * f;
    }
    bool isEmissive() const override {
        if (facTex_) return a_->isEmissive() || b_->isEmissive();
        return (fac_ < 1.0f && a_->isEmissive()) || (fac_ > 0.0f && b_->isEmissive());
    }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps = a_->backendCapabilities();
        caps.gpuApproximate = true;
        caps.notes = "Mix Shader: GPU renders child A only (CPU mixes both); " + caps.notes;
        return caps;
    }
};

}  // namespace astroray
