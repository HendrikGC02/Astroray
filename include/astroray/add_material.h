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
// GPU (#1072, generalised by #995): the closure-graph evaluator normalises lobe
// weights (pkg170), so an Add cannot be one merged graph. An Add / Mix node tree is
// lowered by closure_mix.h lowerClosureTree: its first BSDF leaf uploads at this
// material's id, the other leaves as hidden GMaterials, plus a GClosureTree entry
// (GMaterial::closureTree holds its index + 1); the wavefront shade kernel (the
// HasAdd=true variants only, stage_shade_add.cu) then evaluates f = sum w_i f_i with
// the mixture pdf, exactly the CPU scheme above for an Add of two BSDFs. Cycles picks
// closures proportional to sample_weight (surface_shader_bsdf_bssrdf_pick,
// kernel/integrator/surface_shader.h, Apache-2.0); the mixture pdf keeps the estimator
// unbiased for any selection probabilities (Veach 1997 Eq. 9.15). A tree that does not
// lower keeps the old behaviour: its first BSDF leaf only, reported by the addon.
// ============================================================================

#include <algorithm>
#include <random>
#include "raytracer.h"
#include "closure_mix.h"
#include "light_path_mix.h"
#include "shader_vm.h"

namespace astroray {

class AddMaterial : public ClosureNodeMaterial {
public:
    AddMaterial(std::shared_ptr<Material> a, std::shared_ptr<Material> b)
        : ClosureNodeMaterial(std::move(a), std::move(b)) {}

    // #995: eval / pdf / sample / emission / shadowAlpha are the shared closure node
    // (closure_mix.h) with wA = wB = 1: f = f_A + f_B, child pick 1/2 when both have a
    // BSDF (identical to the #955 scheme above), the BSDF child when the other is a
    // pure emitter.
    void weights(const HitRecord&, const Vec3&, float& wA, float& wB) const override {
        wA = 1.0f;
        wB = 1.0f;
    }
    Vec3 getEmission() const override { return a_->getEmission() + b_->getEmission(); }
    bool isEmissive() const override { return a_->isEmissive() || b_->isEmissive(); }
};

}  // namespace astroray
