#pragma once
// ============================================================================
// #955 -- Add Shader(A, B): the closures of both children ADD (weights are not
// normalised). Cycles kernel/svm/closure.h svm_node_add_closure (Apache-2.0):
// the two closure trees are concatenated with their own weights, so the BSDF is
// f = f_A + f_B (Mix Shader, by contrast, weights them (1-fac), fac).
//
// CPU: eval / evalSpectral are the exact sum. Sampling is one-sample MIS over
// the two children (Veach 1997 Eq. 9.15 one-sample model, balance heuristic):
// pick a child with probability 1/2, sample it, then return the SUMMED f and
// the MIXTURE pdf 0.5 (pdf_A + pdf_B), so f/pdf is an unbiased estimate of the
// sum. A delta child sample cannot be summed with the other child's eval (which
// is 0 for deltas), so it is returned alone with its pdf scaled by the 1/2
// selection probability.
//
// GPU (#1072): the closure-graph evaluator normalises lobe weights (pkg170), so an
// Add cannot be one merged graph. A summable pair (gpuSummable()) uploads child A at
// this material's id and child B as a hidden second GMaterial (GMaterial::addPartner
// holds its index + 1); the wavefront shade kernel (the HasAdd=true variants only, stage_shade_add.cu) then
// evaluates f = f_A + f_B, pdf = 0.5 (pdf_A + pdf_B) and samples a child with
// probability 1/2, exactly the CPU scheme above. Cycles picks closures proportional
// to sample_weight (surface_shader_bsdf_bssrdf_pick, kernel/integrator/surface_shader.h,
// Apache-2.0); this is the equal-weight special case, and the mixture pdf keeps the
// estimator unbiased for any selection probabilities (Veach 1997 Eq. 9.15). A pair
// that is not summable keeps the old behaviour: child A only, reported by the addon.
// ============================================================================

#include <algorithm>
#include <random>
#include "raytracer.h"
#include "light_path_mix.h"
#include "shader_vm.h"

namespace astroray {

class AddMaterial : public Material {
    std::shared_ptr<Material> a_, b_;

public:
    AddMaterial(std::shared_ptr<Material> a, std::shared_ptr<Material> b)
        : a_(std::move(a)), b_(std::move(b)) {}

    const std::shared_ptr<Material>& childA() const { return a_; }
    const std::shared_ptr<Material>& childB() const { return b_; }

    // ---- exact CPU sum ------------------------------------------------------
    Vec3 eval(const HitRecord& r, const Vec3& wo, const Vec3& wi) const override {
        return a_->eval(r, wo, wi) + b_->eval(r, wo, wi);
    }
    float pdf(const HitRecord& r, const Vec3& wo, const Vec3& wi) const override {
        return 0.5f * (a_->pdf(r, wo, wi) + b_->pdf(r, wo, wi));
    }
    BSDFSample sample(const HitRecord& r, const Vec3& wo, std::mt19937& g) const override {
        const bool pickB = std::uniform_real_distribution<float>(0.0f, 1.0f)(g) < 0.5f;
        const Material& c = pickB ? *b_ : *a_;
        const Material& o = pickB ? *a_ : *b_;
        BSDFSample s = c.sample(r, wo, g);
        if (s.pdf <= 0.0f) return s;
        if (s.isDelta) { s.pdf *= 0.5f; return s; }
        s.f = s.f + o.eval(r, wo, s.wi);
        s.pdf = 0.5f * (s.pdf + o.pdf(r, wo, s.wi));
        return s;
    }
    SampledSpectrum evalSpectral(const HitRecord& r, const Vec3& wo, const Vec3& wi,
                                 const SampledWavelengths& l) const override {
        return a_->evalSpectral(r, wo, wi, l) + b_->evalSpectral(r, wo, wi, l);
    }
    BSDFSampleSpectral sampleSpectral(const HitRecord& r, const Vec3& wo, std::mt19937& g,
                                      SampledWavelengths& l) const override {
        const bool pickB = std::uniform_real_distribution<float>(0.0f, 1.0f)(g) < 0.5f;
        const Material& c = pickB ? *b_ : *a_;
        const Material& o = pickB ? *a_ : *b_;
        BSDFSampleSpectral s = c.sampleSpectral(r, wo, g, l);
        if (s.pdf <= 0.0f) return s;
        if (s.isDelta) { s.pdf *= 0.5f; return s; }
        s.f_spectral = s.f_spectral + o.evalSpectral(r, wo, s.wi, l);
        s.pdf = 0.5f * (s.pdf + o.pdf(r, wo, s.wi));
        return s;
    }

    // ---- emission adds too --------------------------------------------------
    Vec3 emitted(const HitRecord& r) const override { return a_->emitted(r) + b_->emitted(r); }
    Vec3 getEmission() const override { return a_->getEmission() + b_->getEmission(); }
    bool isEmissive() const override { return a_->isEmissive() || b_->isEmissive(); }
    SampledSpectrum emittedSpectral(const HitRecord& r, const SampledWavelengths& l) const override {
        return a_->emittedSpectral(r, l) + b_->emittedSpectral(r, l);
    }

    bool isTransmissive() const override { return a_->isTransmissive() || b_->isTransmissive(); }
    bool isGlossy() const override { return a_->isGlossy() || b_->isGlossy(); }
    // Cycles sums the closure weights: each child's transparent weight is (1 - alpha_i),
    // so the summed transparency is (1-aA)+(1-aB) and the opacity max(0, aA + aB - 1).
    float shadowAlpha(const HitRecord& r) const override {
        return std::max(0.0f, a_->shadowAlpha(r) + b_->shadowAlpha(r) - 1.0f);
    }
    // #1045: a smooth conductor + smooth conductor stays delta-only; anything else has a lobe.
    bool isDeltaOnly() const override { return a_->isDeltaOnly() && b_->isDeltaOnly(); }
    // Forwarded to A (a Light Path switch nested under Add keeps child A's branch; the
    // addon reports it).
    std::shared_ptr<Material> lightPathSelect(const lightpath::PathContext& c) const override {
        return a_->lightPathSelect(c);
    }
    // ---- GPU upload / parameter queries: child A at this id; child B is the partner ----
    Vec3 getAlbedo() const override { return a_->getAlbedo(); }  // scene_upload reads it for the GMaterial
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
    // #1072: can the wavefront GPU sum A and B? Both must be plain, opaque, non-emissive
    // materials whose GPU shade needs no per-hit data beyond their own GMaterial: the
    // partner gets no texture / scalar-program / normal-map override, and a transparent
    // or emissive child would need the (CPU) shadowAlpha / emitted sums.
    static bool gpuSummableChild(const Material& m) {
        if (dynamic_cast<const AddMaterial*>(&m) || dynamic_cast<const LightPathMixMaterial*>(&m))
            return false;
        const MaterialBackendCapabilities c = m.backendCapabilities();
        if (!c.gpu || c.gpuApproximate || m.isEmissive() || m.isDispersive()) return false;
        if (m.normalMapInner() || m.normalMapTexture() || m.bumpMapTexture() || m.hairGPUParams().isHair)
            return false;
        for (int s = 0; s <= svm::SCALAR_BASE_COLOR; ++s)
            if (m.scalarProgram(s)) return false;
        const MaterialClosureGraph g = m.closureGraph();
        for (int i = 0; i < g.count(); ++i)
            if (g.closure(i).alpha < 1.0f || g.closure(i).type == MaterialClosureType::Emission)
                return false;
        return true;
    }
    bool gpuSummable() const { return gpuSummableChild(*a_) && gpuSummableChild(*b_); }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps = a_->backendCapabilities();
        if (gpuSummable()) {
            caps.notes = "Add Shader: GPU sums both closures (#1072); " + caps.notes;
        } else {
            caps.gpuApproximate = true;
            caps.notes = "Add Shader: GPU renders child A only (CPU sums both); " + caps.notes;
        }
        return caps;
    }
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

}  // namespace astroray
