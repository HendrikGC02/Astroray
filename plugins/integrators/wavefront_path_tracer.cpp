// wavefront_path_tracer.cpp — pkg55-B' plugin registration (spec §6).
//
// The wavefront is a whole-frame GPU SCHEDULING of the same light transport
// the production spectral path tracer computes (the CPU shared kernel
// src/cpu/wavefront/path_kernel.cpp mirrors Renderer::pathTraceSpectral, and
// the GPU stage_advance halves mirror the CPU kernel). The Integrator
// interface is per-ray (sampleFull), so the CPU side of this plugin
// DELEGATES to the registered "path_tracer" (SpectralPathTracer) — the very
// integrator the wavefront program is gated against. Selecting this name
// changes only the GPU dispatch: module/blender_module.cpp routes
// "wavefront_path_tracer" + set_use_gpu(True) to cuda_wavefront_render
// (regeneration + bucketed shade + shadow stage) instead of the megakernel.
//
// Decorator pattern: forwards every virtual to the wrapped instance so CPU
// renders, AOVs, and params behave exactly like "path_tracer".

#include "astroray/register.h"
#include "astroray/integrator.h"

#include <memory>
#include <stdexcept>

namespace {

class WavefrontPathTracer : public Integrator {
    std::shared_ptr<Integrator> inner_;

public:
    explicit WavefrontPathTracer(const astroray::ParamDict& p) {
        inner_ = astroray::IntegratorRegistry::instance().create("path_tracer", p);
        if (!inner_) {
            throw std::runtime_error(
                "wavefront_path_tracer: failed to create the wrapped "
                "path_tracer integrator");
        }
    }

    void beginFrame(Renderer& scene, Camera& cam) override {
        inner_->beginFrame(scene, cam);
    }
    void endFrame() override { inner_->endFrame(); }

    std::unordered_map<std::string, float> debugStats() const override {
        return inner_->debugStats();
    }

    IntegratorCapabilities capabilities() const override {
        // GPU support is the point of this name: the dispatch in
        // module/blender_module.cpp routes it to the wavefront pipeline
        // (cuda_wavefront_render). CPU falls back to SpectralPathTracer.
        return {true, ""};
    }

    void setMaxDepth(int depth) override { inner_->setMaxDepth(depth); }

    SampleResult sampleFull(const Ray& ray, std::mt19937& gen) override {
        return inner_->sampleFull(ray, gen);
    }
};

}  // namespace

ASTRORAY_REGISTER_INTEGRATOR("wavefront_path_tracer", WavefrontPathTracer)
